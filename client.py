import os
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
from flask import Flask, jsonify, request
from dataclasses import dataclass, asdict
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")

FILE_OPERATION_FILE = "/logs/file_operation_log.csv"

IS_LOCKED_DOWN = False
WRITE_PERMISSION = threading.Event()
WRITE_PERMISSION.set()  # Initially allowed


# send msg to RabbitMQ
def send_msg(file_path, entropy, event_type):
    try:
        # init short connection for every sending
        credentials = pika.PlainCredentials("guest", "guest")
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
        )
        channel = connection.channel()

        channel.queue_declare(queue="file_events")

        payload = {
            "client_id": CLIENT_ID,
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


def calculate_entropy(data):
    if not data:
        return 0

    # shannon entropy, to see how 'random' a file is
    entropy = 0
    total_len = len(data)

    counts = Counter(data)

    for count in counts.values():
        p_x = count / total_len
        if p_x > 0:
            entropy += -p_x * math.log(p_x, 2)

    return entropy


class EntropyMonitor(FileSystemEventHandler):
    def _should_ignore(self, filename):
        return filename.endswith(".locked") or ".tmp" in filename

    def on_modified(self, event):
        # only monitor file
        if IS_LOCKED_DOWN or event.is_directory:
            return  # don't report when lock_down
        filename = event.src_path

        if self._should_ignore(filename):
            return

        try:
            with open(filename, "rb") as f:  # Attempt to open and read the file
                data = f.read()
                entropy = calculate_entropy(data)

                # only report if entropy is high
                if entropy > 0:
                    send_msg(filename, entropy, "MODIFY")
        except Exception as e:
            # File in use, ignore this error but log for debugging.
            print(f"[WARNING] Failed to read or process file {filename}: {e}")

    def on_created(self, event):
        if IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path

        if self._should_ignore(filename):
            return

        # For newly created files, calculate entropy.
        # If the file was just created and not fully written
        # or initial content has zero entropy, it is not reported.
        try:
            # let system complete file writing.
            time.sleep(0.05)
            with open(filename, "rb") as f:
                data = f.read()
                entropy = calculate_entropy(data)

                # Only report if entropy is high
                if entropy > 0:
                    send_msg(filename, entropy, "CREATE")
        except FileNotFoundError:
            # The file might have been deleted or moved immediately after reading.
            print(f"[WARNING] Created file {filename} disappeared before reading.")
        except Exception as e:
            print(f"[WARNING] Failed to read or process newly created file {filename}: {e}")

    def on_deleted(self, event):
        if IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path

        if self._should_ignore(filename):
            return

        # For deleted files, entropy cannot be calculated.
        # Report the deletion event.
        send_msg(filename, 0, "DELETE")


# listen to RabbitMQ
def lock_down_listener():
    global IS_LOCKED_DOWN
    while True:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.queue_declare(queue="commands")

            def callback(ch, method, properties, body):
                global IS_LOCKED_DOWN
                msg = json.loads(body)

                IS_LOCKED_DOWN = True
                print(f"[LOCK_DOWN] Command received! Isolating {CLIENT_ID}...")
                # report ok
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")

            channel.basic_consume(queue="commands", on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            time.sleep(5)


# local IO
def _local_create(filename, content):
    filepath = os.path.join(MONITOR_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)


def _local_write(filename, content):
    filepath = os.path.join(MONITOR_DIR, filename)
    with open(filepath, "a") as f:
        f.write(content)
    with open(filepath, "r") as f:
        return f.read()


def _local_delete(filename):
    filepath = os.path.join(MONITOR_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


# rabbitMQ sync, `finance_sync`, all nodes manage files only by this thread.
def sync_listener():
    while True:
        try:
            # connect
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")

            result = channel.queue_declare(queue="", exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange="finance_sync", queue=queue_name)

            def callback(ch, method, properties, body):
                msg = json.loads(body)
                sender = msg.get("sender")
                if sender == CLIENT_ID:
                    return

                # wait for permission (Snapshot consistency)
                WRITE_PERMISSION.wait()

                op = msg.get("operation")
                filename = msg.get("filename")
                content = msg.get("content", "")

                try:
                    if op == "CREATE":
                        _local_create(filename, content)
                    elif op == "WRITE":
                        _local_write(filename, content)
                    elif op == "DELETE":
                        _local_delete(filename)

                    # send ACK
                    if properties.reply_to:
                        reply_props = pika.BasicProperties(correlation_id=properties.correlation_id)
                        ch.basic_publish(
                            exchange="",
                            routing_key=properties.reply_to,
                            properties=reply_props,
                            body=json.dumps({"status": "ACK", "sender": CLIENT_ID}),
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
        pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
    )
    channel = connection.channel()

    channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
    result = channel.queue_declare(queue="", exclusive=True)
    callback_queue = result.method.queue

    # publish command
    corr_id = str(uuid.uuid4())
    payload = {
        "sender": CLIENT_ID,
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


app = Flask(__name__)


# simulate being attacked
@app.route("/attack", methods=["POST"])
def trigger_attack():
    def run_encryption():
        print(f"[RANSOMWARE] Attack started on {CLIENT_ID}...")
        for root, _, files in os.walk(MONITOR_DIR):
            for file in files:
                if file.endswith(".locked"):
                    continue

                filepath = os.path.join(root, file)
                try:
                    # read original file
                    with open(filepath, "rb") as f:
                        data = f.read()

                    # generate high-entropy random data
                    # (because real AES encryption is of high overhead)
                    encrypted = os.urandom(len(data))
                    with open(filepath, "wb") as f:
                        f.write(encrypted)

                    # rename
                    new_filepath = filepath + ".locked"
                    os.rename(filepath, new_filepath)

                    print(f"Encrypted: {file}")

                    # slow down so watchdog does not miss anything
                    # simulating ransomware one by one
                    time.sleep(0.5)

                except Exception as e:
                    print(f"Failed to encrypt {file}: {e}")

    # new a thread to encrypt
    threading.Thread(target=run_encryption).start()
    return jsonify({"status": "infected", "target": CLIENT_ID})


# simulate normal operation
@app.route("/normal", methods=["POST"])
def trigger_normal():
    global IS_LOCKED_DOWN
    IS_LOCKED_DOWN = False

    target_file = None
    for root, _, files in os.walk(MONITOR_DIR):
        if files:
            target_file = os.path.join(root, files[0])
            break

    if target_file:
        try:
            with open(target_file, "a") as f:
                f.write("\nhello world")
            print(f"[NORMAL] Modified {target_file}")
            return jsonify({"status": "success", "file": target_file})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "no_files_found"}), 404

# listen to gRPC for trigger lockdown
class LockdownServicer(lockdown_pb2_grpc.LockdownServiceServicer):
    def TriggerLockdown(self, request, context):
        if request.targeted_node != CLIENT_ID and request.targeted_node != "ALL":
            msg = f"Ignored. Lockdown meant for {request.targeted_node}, I am {CLIENT_ID}."
            print(f"[{CLIENT_ID}]: {msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=msg)
        
        print(f"[{CLIENT_ID}] received. threat_id: {request.threat_id}, reason: {request.reason}")
        
        try:
            # simple lockdown, read only
            self.lock_directory_readonly(MONITOR_DIR)
            IS_LOCKED_DOWN = True
            success_msg = f"Directory {MONITOR_DIR} successfully locked (Read-Only)."
            print(f"[{CLIENT_ID}]: {success_msg}\n")
            return lockdown_pb2.LockdownResponse(success=True, status_message=success_msg)
        except Exception as e:
            error_msg = f"Failed to lock directory: {e}"
            print(f"[{CLIENT_ID}]: {error_msg}")
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
    server.add_insecure_port('[::]:50051')
    server.start()
    print(f"[{CLIENT_ID}] gRPC server started on port 50051, waiting for lockdown commands if needs...")
    server.wait_for_termination()

# requests and responses
@dataclass
class ReadReq:
    filename: str


@dataclass
class WriteReq:
    filename: str
    content: str


@dataclass
class CreateReq:
    filename: str
    content: str = ""


@dataclass
class DeleteReq:
    filename: str


@dataclass
class Response:
    status: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


# Snapshot Coordination Endpoints
@app.route("/snapshot/prepare", methods=["POST"])
def snapshot_prepare():
    # pause new write operations
    WRITE_PERMISSION.clear()
    return jsonify({"status": "ready"})


@app.route("/snapshot/commit", methods=["POST"])
def snapshot_commit():
    # resume write operations
    WRITE_PERMISSION.set()
    return jsonify({"status": "resumed"})


@app.route("/snapshot/data", methods=["GET"])
def snapshot_data():
    # return all files in MONITOR_DIR encoded in base64
    backup_data = {}
    for root, _, files in os.walk(MONITOR_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, MONITOR_DIR)
            try:
                with open(filepath, "rb") as f:
                    content = base64.b64encode(f.read()).decode("utf-8")
                backup_data[rel_path] = content
            except Exception as e:
                print(f"[WARNING] Snapshot read failed for {file}: {e}")
    return jsonify(backup_data)


# param: filename
# return: file content
@app.route("/read", methods=["POST"])
def read_file():
    try:
        req = ReadReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(MONITOR_DIR, req.filename)
    if not os.path.exists(filepath):
        return jsonify(Response(error="File not found").to_dict()), 404

    try:
        with open(filepath, "r") as f:
            content = f.read()
        return jsonify(Response(status="success", content=content).to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# work only for primary node
# param: filename, content (optional)
# return: success status
@app.route("/create", methods=["POST"])
def create_file():
    WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = CreateReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(MONITOR_DIR, req.filename)
    try:
        _local_create(req.filename, req.content)

        # broadcast to others via RabbitMQ
        broadcast_sync("CREATE", req.filename, req.content)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": CLIENT_ID,
                "filename": req.filename,
                "operation": "CREATE",
                "appended": req.content,
            }

            file_exists = os.path.exists(FILE_OPERATION_FILE)
            with open(FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["timestamp", "client_id", "filename", "operation", "appended"],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(log_entry)

            # notify recovery service
            requests.post("http://recovery-service:8080/archive", json=log_entry, timeout=2)
        except Exception as e:
            print(f"[WARNING] Logging/Archive failed: {e}")

        return jsonify(Response(status="success", message="File created").to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# work only for primary node
# param: filename and content to be appended(append only)
# return: file content after modification
@app.route("/write", methods=["POST"])
def write_file():
    WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = WriteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename and content are required").to_dict()), 400

    filepath = os.path.join(MONITOR_DIR, req.filename)
    try:
        new_content = _local_write(req.filename, req.content)

        # broadcast to others via RabbitMQ
        broadcast_sync("WRITE", req.filename, req.content)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": CLIENT_ID,
                "filename": req.filename,
                "operation": "MODIFY",
                "appended": req.content,
            }

            file_exists = os.path.exists(FILE_OPERATION_FILE)
            with open(FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["timestamp", "client_id", "filename", "operation", "appended"],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(log_entry)

            # notify recovery service
            requests.post("http://recovery-service:8080/archive", json=log_entry, timeout=2)
        except Exception as e:
            print(f"[WARNING] Logging/Archive failed: {e}")

        return jsonify(Response(status="success", content=new_content).to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# work only for primary node
# param: filename
# return: success status
@app.route("/delete", methods=["POST"])
def delete_file():
    WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = DeleteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(MONITOR_DIR, req.filename)
    try:
        if not os.path.exists(filepath):
            return jsonify(Response(error="File not found").to_dict()), 404

        _local_delete(req.filename)

        # broadcast to others via RabbitMQ
        broadcast_sync("DELETE", req.filename)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": CLIENT_ID,
                "filename": req.filename,
                "operation": "DELETE",
                "appended": "",
            }

            file_exists = os.path.exists(FILE_OPERATION_FILE)
            with open(FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["timestamp", "client_id", "filename", "operation", "appended"],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(log_entry)

            # notify recovery service
            requests.post("http://recovery-service:8080/archive", json=log_entry, timeout=2)
        except Exception as e:
            print(f"[WARNING] Logging/Archive failed: {e}")

        return jsonify(Response(status="success", message="File deleted").to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


if __name__ == "__main__":
    print(f"[🍺] Client started on {CLIENT_ID}. Watching {MONITOR_DIR}")
    # listen command from detection engine
    threading.Thread(target=lock_down_listener, daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()    # listen sync command from other clients
    threading.Thread(target=sync_listener, daemon=True).start()

    # what to do when file operation monitored
    event_handler = EntropyMonitor()

    # initialize watchdog
    # operation observed, call event_handler
    # moniter `/data`
    # also `/data`'s sub-dir
    observer = Observer()
    observer.schedule(event_handler, path=MONITOR_DIR, recursive=True)
    observer.start()

    # start waiting for attacker(?)
    app.run(host="0.0.0.0", port=5000)
