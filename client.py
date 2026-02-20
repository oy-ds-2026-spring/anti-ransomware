import os
import time
import math
import json
import csv
import base64
import threading
import pika
import random
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

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

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


# requests and responses
@dataclass
class ReadReq:
    filename: str


@dataclass
class WriteReq:
    filename: str
    content: str
    propagated: bool = False


@dataclass
class CreateReq:
    filename: str
    content: str = ""
    propagated: bool = False


@dataclass
class DeleteReq:
    filename: str
    propagated: bool = False


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
        with open(filepath, "w") as f:
            f.write(req.content)

        # sync with other 3 nodes
        if not req.propagated:
            for node in FINANCE_NODES:
                # skip self
                if CLIENT_ID in node:
                    continue
                try:
                    requests.post(
                        f"http://{node}:5000/create",
                        json=asdict(
                            CreateReq(filename=req.filename, content=req.content, propagated=True)
                        ),
                        timeout=5,
                    )
                except Exception as e:
                    print(f"[WARNING] Propagation failed to {node}: {e}")

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
        with open(filepath, "a") as f:
            f.write(req.content)
        with open(filepath, "r") as f:
            new_content = f.read()

        # sync with other 3 nodes
        if not req.propagated:
            for node in FINANCE_NODES:
                # skip self
                if CLIENT_ID in node:
                    continue
                try:
                    requests.post(
                        f"http://{node}:5000/write",
                        json=asdict(
                            WriteReq(filename=req.filename, content=req.content, propagated=True)
                        ),
                        timeout=5,
                    )
                except Exception as e:
                    print(f"[WARNING] Propagation failed to {node}: {e}")

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
        if os.path.exists(filepath):
            os.remove(filepath)
        else:
            return jsonify(Response(error="File not found").to_dict()), 404

        # sync with other 3 nodes
        if not req.propagated:
            for node in FINANCE_NODES:
                # skip self
                if CLIENT_ID in node:
                    continue
                try:
                    requests.post(
                        f"http://{node}:5000/delete",
                        json=asdict(DeleteReq(filename=req.filename, propagated=True)),
                        timeout=5,
                    )
                except Exception as e:
                    print(f"[WARNING] Propagation failed to {node}: {e}")

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
    threading.Thread(target=lock_down_listener, daemon=True).start()

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
