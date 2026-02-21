import os
import time
import threading
import base64
import csv
import requests
from flask import Flask, jsonify, request

import config
import utils
from models import ReadReq, WriteReq, CreateReq, DeleteReq, Response
import rabbitmq_handler

app = Flask(__name__)


# simulate being attacked
@app.route("/attack", methods=["GET"])
def trigger_attack():
    def run_encryption():
        print(f"[RANSOMWARE] Attack started on {config.CLIENT_ID}...")
        for root, _, files in os.walk(config.MONITOR_DIR):
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
    return jsonify({"status": "infected", "target": config.CLIENT_ID})


# simulate normal operation
@app.route("/normal", methods=["POST"])
def trigger_normal():
    config.IS_LOCKED_DOWN = False

    target_file = None
    for root, _, files in os.walk(config.MONITOR_DIR):
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


@app.route("/unlock", methods=["GET", "POST"])
def unlock_system():
    config.IS_LOCKED_DOWN = False
    print("[RECOVERY] System unlocked")
    return jsonify({"status": "unlocked"})


# snapshot ###########################################


# Snapshot Coordination Endpoints
@app.route("/snapshot/prepare", methods=["POST"])
def snapshot_prepare():
    # pause new write operations
    config.WRITE_PERMISSION.clear()
    return jsonify({"status": "ready"})


@app.route("/snapshot/commit", methods=["POST"])
def snapshot_commit():
    # resume write operations
    config.WRITE_PERMISSION.set()
    return jsonify({"status": "resumed"})


@app.route("/snapshot/data", methods=["GET"])
def snapshot_data():
    # return all files in MONITOR_DIR encoded in base64
    backup_data = {}
    for root, _, files in os.walk(config.MONITOR_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, config.MONITOR_DIR)
            try:
                with open(filepath, "rb") as f:
                    content = base64.b64encode(f.read()).decode("utf-8")
                backup_data[rel_path] = content
            except Exception as e:
                print(f"[WARNING] Snapshot read failed for {file}: {e}")
    return jsonify(backup_data)


# file system remote access ##########################


# param: filename
# return: file content
@app.route("/read", methods=["POST"])
def read_file():
    try:
        req = ReadReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(config.MONITOR_DIR, req.filename)
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
    config.WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = CreateReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(config.MONITOR_DIR, req.filename)
    try:
        utils.local_create(req.filename, req.content)

        # broadcast to others via RabbitMQ
        rabbitmq_handler.broadcast_sync("CREATE", req.filename, req.content)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": config.CLIENT_ID,
                "filename": req.filename,
                "operation": "CREATE",
                "appended": req.content,
            }

            file_exists = os.path.exists(config.FILE_OPERATION_FILE)
            with open(config.FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
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
    config.WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = WriteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename and content are required").to_dict()), 400

    filepath = os.path.join(config.MONITOR_DIR, req.filename)
    try:
        new_content = utils.local_write(req.filename, req.content)

        # broadcast to others via RabbitMQ
        rabbitmq_handler.broadcast_sync("WRITE", req.filename, req.content)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": config.CLIENT_ID,
                "filename": req.filename,
                "operation": "MODIFY",
                "appended": req.content,
            }

            file_exists = os.path.exists(config.FILE_OPERATION_FILE)
            with open(config.FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
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
    config.WRITE_PERMISSION.wait()  # Wait if snapshot is in progress
    try:
        req = DeleteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(config.MONITOR_DIR, req.filename)
    try:
        if not os.path.exists(filepath):
            return jsonify(Response(error="File not found").to_dict()), 404

        utils.local_delete(req.filename)

        # broadcast to others via RabbitMQ
        rabbitmq_handler.broadcast_sync("DELETE", req.filename)

        # log locally and notify recovery service
        try:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "client_id": config.CLIENT_ID,
                "filename": req.filename,
                "operation": "DELETE",
                "appended": "",
            }

            file_exists = os.path.exists(config.FILE_OPERATION_FILE)
            with open(config.FILE_OPERATION_FILE, "a", newline="", encoding="utf-8") as f:
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
