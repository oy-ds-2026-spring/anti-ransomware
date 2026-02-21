import os
import stat
import time
import threading
import base64
import csv
import requests
from flask import Flask, jsonify, request

from client import config
from client import utils
from client.models import ReadReq, WriteReq, CreateReq, DeleteReq, Response
from client import rabbitmq_handler
import security
from logger import Logger

app = Flask(__name__)


# log locally and notify recovery service
def _log_and_archive(filename, operation, appended=""):
    try:
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": config.CLIENT_ID,
            "filename": filename,
            "operation": operation,
            "appended": appended,
        }
        file_exists = os.path.exists(config.FILE_OPERATION_LOG)
        with open(config.FILE_OPERATION_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "client_id", "filename", "operation", "appended"]
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(log_entry)

        # notify recovery service
        requests.post("http://recovery-service:8080/archive", json=log_entry, timeout=2)
    except Exception as e:
        Logger.warning(f"Logging/Archive failed: {e}")


def _run_encryption():
    Logger.ransomware(f"Attack started on {config.CLIENT_ID}...")
    for root, _, files in os.walk(config.MONITOR_DIR):
        for file in files:
            if file.endswith(".locked"):
                continue
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "rb") as f:
                    data = f.read()
                with open(filepath, "wb") as f:
                    f.write(os.urandom(len(data)))
                os.rename(filepath, filepath + ".locked")
                Logger.encrypted(f"{file}")
                time.sleep(0.5)
            except Exception as e:
                Logger.warning(f"Failed to encrypt {file}: {e}")


# simulate being attacked
@app.route("/attack", methods=["GET"])
def trigger_attack():
    threading.Thread(target=_run_encryption).start()
    return jsonify({"status": "infected", "target": config.CLIENT_ID})


@app.route("/unlock", methods=["GET", "POST"])
def unlock_system():
    # config.IS_LOCKED_DOWN = False
    # Logger.unlock("System unlocked")
    # return jsonify({"status": "unlocked"})
    success, message = security.execute_unlock(
        trigger_source="API Request", 
        reason="Manual unlock via /unlock endpoint"
    )
    
    if success:
        return jsonify({"status": "unlocked", "message": message})
    else:
        return jsonify({"status": "error", "message": message}), 500


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
                Logger.warning(f"Snapshot read failed for {file}: {e}")
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

        current_clock = utils.increment_clock()
        # broadcast to others via RabbitMQ
        rabbitmq_handler.broadcast_sync("CREATE", req.filename, req.content)

        _log_and_archive(req.filename, "CREATE", req.content)

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

        current_clock = utils.increment_clock()
        # broadcast to others via RabbitMQ # with clock
        rabbitmq_handler.broadcast_sync("WRITE", req.filename, req.content, current_clock)

        _log_and_archive(req.filename, "MODIFY", req.content)

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
        
        current_clock = utils.increment_clock()
        # broadcast to others via RabbitMQ # with clock
        rabbitmq_handler.broadcast_sync("DELETE", req.filename, current_clock)

        _log_and_archive(req.filename, "DELETE", "")

        return jsonify(Response(status="success", message="File deleted").to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500
