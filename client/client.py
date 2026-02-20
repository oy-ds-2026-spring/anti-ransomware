import os
import time
import math
import json
import threading
import pika
import random
from flask import Flask, jsonify
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter
from collections import deque
import stat
import time
import math
import json
import csv
import uuid
import base64
import threading
import pika
import random
import grpc
import logging
from concurrent import futures
import lockdown_pb2
import lockdown_pb2_grpc
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter
import config
import routes
import utils
from monitor import EntropyMonitor


# send msg to RabbitMQ
def send_msg(file_path, entropy, event_type):
    try:
        # init short connection for every sending
        credentials = pika.PlainCredentials("guest", "guest")
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
        )
        channel = connection.channel()

        channel.queue_declare(queue="file_events")

        payload = {
            "client_id": config.CLIENT_ID,
            "file_path": file_path,
            "entropy": entropy,
            "event_type": event_type,
            "timestamp": time.time(),
        }

        channel.basic_publish(exchange="", routing_key="file_events", body=json.dumps(payload))
        print(
            f"[SENT] {file_path} | Entropy: {entropy:.2f} | Event: {event_type}"
        )  # Add event type to output
        connection.close()
    except Exception as e:
        print(f"[ERROR] RabbitMQ Error: {e}")


# listen to RabbitMQ
def lock_down_listener():
    while True:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.queue_declare(queue="commands")

            def callback(ch, method, properties, body):
                msg = json.loads(body)

                config.IS_LOCKED_DOWN = True
                print(f"[LOCK_DOWN] Command received! Isolating {config.CLIENT_ID}...")
                # report ok
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")

            channel.basic_consume(queue="commands", on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            time.sleep(5)


# rabbitMQ sync, `finance_sync`, all nodes manage files only by this thread.
def sync_listener():
    while True:
        try:
            # connect
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")

            result = channel.queue_declare(queue="", exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange="finance_sync", queue=queue_name)

            def callback(ch, method, properties, body):
                msg = json.loads(body)
                sender = msg.get("sender")
                if sender == config.CLIENT_ID:
                    return

                # wait for permission (Snapshot consistency)
                config.WRITE_PERMISSION.wait()

                op = msg.get("operation")
                filename = msg.get("filename")
                content = msg.get("content", "")

                try:
                    if op == "CREATE":
                        utils.local_create(filename, content)
                    elif op == "WRITE":
                        utils.local_write(filename, content)
                    elif op == "DELETE":
                        utils.local_delete(filename)

                    # send ACK
                    if properties.reply_to:
                        reply_props = pika.BasicProperties(correlation_id=properties.correlation_id)
                        ch.basic_publish(
                            exchange="",
                            routing_key=properties.reply_to,
                            properties=reply_props,
                            body=json.dumps({"status": "ACK", "sender": config.CLIENT_ID}),
                        )
                        print(f"[SYNC_ACK] Sent ACK for {op}, {filename}")
                except Exception as e:
                    print(f"[ERROR] Sync processing failed: {e}")

            # starts listening
            channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
            print("[SYNC] Listener started")
            channel.start_consuming()
        except Exception as e:
            print(f"[ERROR] Sync listener connection lost: {e}")
            time.sleep(5)


# primary client write node send function
def broadcast_sync(operation, filename, content=""):
    # connect
    credentials = pika.PlainCredentials("guest", "guest")
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
    )
    channel = connection.channel()

    channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
    result = channel.queue_declare(queue="", exclusive=True)
    callback_queue = result.method.queue

    # publish command
    corr_id = str(uuid.uuid4())
    payload = {
        "sender": config.CLIENT_ID,
        "operation": operation,
        "filename": filename,
        "content": content,
    }

    channel.basic_publish(
        exchange="finance_sync",
        routing_key="",
        properties=pika.BasicProperties(
            reply_to=callback_queue,
            correlation_id=corr_id,
        ),
        body=json.dumps(payload),
    )
    print(f"[SYNC] request for {operation}, {filename}, {content}")

    # starts to count ACK number
    ack_count = 0

    def on_ack(ch, method, props, body):
        nonlocal ack_count
        if props.correlation_id == corr_id:
            ack_count += 1

    # starts listening ack
    channel.basic_consume(queue=callback_queue, on_message_callback=on_ack, auto_ack=True)

    start_time = time.time()
    # wait for 3 ACKs (assuming 4 nodes total, 1 sender, 3 receivers)
    while ack_count < 3:
        connection.process_data_events(time_limit=1)
        if time.time() - start_time > 10:
            print(f"[WARNING] Sync timeout. Received {ack_count}/3 ACKs.")
            break

    print(f"[🍺 SYNC_OK] Received {ack_count} ACKs")
    connection.close()


# listen to gRPC for trigger lockdown
class LockdownServicer(lockdown_pb2_grpc.LockdownServiceServicer):
    def TriggerLockdown(self, request, context):
        if request.targeted_node != config.CLIENT_ID and request.targeted_node != "ALL":
            msg = f"Ignored. Lockdown meant for {request.targeted_node}, I am {config.CLIENT_ID}."
            print(f"[{config.CLIENT_ID}]: {msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=msg)

        print(
            f"[{config.CLIENT_ID}] received. threat_id: {request.threat_id}, reason: {request.reason}"
        )

        try:
            # simple lockdown, read only
            self.lock_directory_readonly(config.MONITOR_DIR)
            config.IS_LOCKED_DOWN = True
            success_msg = f"Directory {config.MONITOR_DIR} successfully locked (Read-Only)."
            print(f"[{config.CLIENT_ID}]: {success_msg}\n")
            return lockdown_pb2.LockdownResponse(success=True, status_message=success_msg)
        except Exception as e:
            error_msg = f"Failed to lock directory: {e}"
            print(f"[{config.CLIENT_ID}]: {error_msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=error_msg)

    def lock_directory_readonly(self, path):
        # modify permissions to read-only for all files and directories
        READ_ONLY = stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH
        # dir need execute permission to be accessible, even for read-only
        DIR_READ_ONLY = READ_ONLY | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

        os.chmod(path, DIR_READ_ONLY)
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chmod(os.path.join(root, d), DIR_READ_ONLY)
            for f in files:
                os.chmod(os.path.join(root, f), READ_ONLY)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lockdown_pb2_grpc.add_LockdownServiceServicer_to_server(LockdownServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print(
        f"[{config.CLIENT_ID}] gRPC server started on port 50051, waiting for lockdown commands if needs..."
    )
    server.wait_for_termination()


if __name__ == "__main__":
    print(f"[INFO] Client started on {config.CLIENT_ID}. Watching {config.MONITOR_DIR}")
    utils.fishing(config.MONITOR_DIR)
    # listen command from detection engine
    threading.Thread(target=lock_down_listener, daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()  # listen sync command from other clients
    threading.Thread(target=sync_listener, daemon=True).start()

    # what to do when file operation monitored
    event_handler = EntropyMonitor()

    # initialize watchdog
    # operation observed, call event_handler
    # moniter `/data`
    # also `/data`'s sub-dir
    observer = Observer()
    observer.schedule(event_handler, path=config.MONITOR_DIR, recursive=True)
    observer.start()

    # start waiting for attacker(?)
    routes.app.run(host="0.0.0.0", port=5000)
