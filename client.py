import os
import stat
import time
import math
import json
import threading
import pika
import random
import grpc
import logging
from concurrent import futures
import lockdown_pb2
import lockdown_pb2_grpc
from flask import Flask, jsonify
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")

IS_LOCKED_DOWN = False


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
        print(f"RabbitMQ Error: {e}")


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
            print(f"Failed to read or process file {filename}: {e}")

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
            print(f"Created file {filename} disappeared before reading.")
        except Exception as e:
            print(f"Failed to read or process newly created file {filename}: {e}")

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
                print(f"🔒 [LOCK_DOWN] Command received! Isolating {CLIENT_ID}...")
                # report ok
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")

            channel.basic_consume(queue="commands", on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            time.sleep(5)


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

if __name__ == "__main__":
    print(f"Client started on {CLIENT_ID}. Watching {MONITOR_DIR}")
    threading.Thread(target=lock_down_listener, daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
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
