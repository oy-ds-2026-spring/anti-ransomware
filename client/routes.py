import os
import stat
import time
import multiprocessing
import base64
import csv
import requests
from flask import Flask, jsonify, request
from flasgger import Swagger

from client import config
from client import utils
from client.models import ReadReq, WriteReq, CreateReq, DeleteReq, Response
from client import rabbitmq_handler
from client.security import execute_unlock
from logger import Logger

app = Flask(__name__)
Swagger(app)


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


def _run_encryption(monitor_dir, client_id):
    try:
        # drop privileges to non-root user
        os.setgid(1000)
        os.setuid(1000)
    except Exception as e:
        Logger.error(f"Failed to drop privileges: {e}")
        return  # Exit, no root attack possible

    Logger.ransomware(f"Attack started on {client_id} as non-root user")

    if not os.access(monitor_dir, os.W_OK):
        Logger.error("OS PHYSICAL BLOCK: Attacker lost write access. Process terminating.")
        return

    for root, _, files in os.walk(monitor_dir):
        for file in files:
            if file.endswith(".locked"):
                continue
            filepath = os.path.join(root, file)

            try:
                # If 'Owner Write' (S_IWUSR) is missing, we simulate the Linux Kernel block.
                dir_mode = os.stat(root).st_mode
                if not (dir_mode & stat.S_IWUSR):
                    raise PermissionError(
                        13, f"Permission denied (Blocked by OS Lock): '{filepath}'"
                    )

                with open(filepath, "rb") as f:
                    data = f.read()

                with open(filepath, "wb") as f:
                    f.write(os.urandom(len(data)))

                os.rename(filepath, filepath + ".locked")
                Logger.encrypted(f"{file}")

                time.sleep(0.5)

            except Exception as e:
                Logger.error(f"ATTACKER BLOCKED: {e}")
                if isinstance(e, PermissionError):
                    Logger.info("Attacker process crushed against the physical lock.")
                    return  # Exit the attack process immediately


# simulate being attacked
@app.route("/attack", methods=["GET"])
def trigger_attack():
    """
    Trigger a simulated ransomware attack on this node.
    ---
    tags:
      - Simulation
    responses:
      200:
        description: Attack triggered successfully
        schema:
          type: object
          properties:
            status:
              type: string
            target:
              type: string
    """
    # t = threading.Thread(
    #     target=_run_encryption,
    #     args=(config.MONITOR_DIR, config.CLIENT_ID),
    #     daemon=True
    # )
    # t.start()

    p = multiprocessing.Process(target=_run_encryption, args=(config.MONITOR_DIR, config.CLIENT_ID))
    p.start()

    return jsonify({"status": "infected", "target": config.CLIENT_ID})


@app.route("/unlock", methods=["GET", "POST"])
def unlock_system():
    """
    Unlock the system after a lockdown.
    ---
    tags:
      - Simulation
    responses:
      200:
        description: System unlocked successfully
    """
    success, msg = execute_unlock(
        trigger_source="REST API (/unlock)", reason="Manual reset or Recovery Service command"
    )

    if success:
        return jsonify({"status": "unlocked", "message": msg}), 200
    else:
        return jsonify({"status": "error", "message": msg}), 500


# snapshot ###########################################


# Snapshot Coordination Endpoints
@app.route("/snapshot/prepare", methods=["POST"])
def snapshot_prepare():
    """
    Prepare for a snapshot by pausing write operations.
    ---
    tags:
      - Snapshot
    responses:
      200:
        description: Ready for snapshot
    """
    # pause new write operations
    config.WRITE_PERMISSION.clear()
    return jsonify({"status": "ready"})


@app.route("/snapshot/commit", methods=["POST"])
def snapshot_commit():
    """
    Commit the snapshot and resume write operations.
    ---
    tags:
      - Snapshot
    responses:
      200:
        description: Write operations resumed
    """
    # resume write operations
    config.WRITE_PERMISSION.set()
    return jsonify({"status": "resumed"})


@app.route("/snapshot/data", methods=["GET"])
def snapshot_data():
    """
    Retrieve all files in the monitor directory encoded in base64.
    ---
    tags:
      - Snapshot
    responses:
      200:
        description: Snapshot data retrieved
    """
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
    """
    Read a file's content.
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
    responses:
      200:
        description: File content retrieved
      400:
        description: Invalid request
      404:
        description: File not found
      500:
        description: Internal server error
    """
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
    """
    Create a new file.
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
            content:
              type: string
    responses:
      200:
        description: File created successfully
      400:
        description: Invalid request
      500:
        description: Internal server error
    """
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
    """
    Append content to an existing file.
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
            - content
          properties:
            filename:
              type: string
            content:
              type: string
    responses:
      200:
        description: File written successfully
      400:
        description: Invalid request
      500:
        description: Internal server error
    """
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
    """
    Delete a file.
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
    responses:
      200:
        description: File deleted successfully
      400:
        description: Invalid request
      404:
        description: File not found
      500:
        description: Internal server error
    """
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


# Simple file browser to view /data structure and content
@app.route("/browse", defaults={"req_path": ""})
@app.route("/browse/<path:req_path>")
def browse_fs(req_path):
    """
    Browse the file system of the monitored directory.
    ---
    tags:
      - File Browser
    parameters:
      - in: path
        name: req_path
        type: string
        required: false
        description: The path to browse (relative to monitor dir)
    responses:
      200:
        description: HTML content of the directory listing or file content
      403:
        description: Forbidden
      404:
        description: Not Found
      500:
        description: Internal server error
    """
    base_dir = os.path.abspath(config.MONITOR_DIR)
    abs_path = os.path.abspath(os.path.join(base_dir, req_path))

    # Security check
    if not abs_path.startswith(base_dir):
        return "Forbidden", 403

    if not os.path.exists(abs_path):
        return "Not Found", 404

    if os.path.isfile(abs_path):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return f"<h3>File: {req_path}</h3><pre>{content}</pre>"
        except Exception as e:
            return f"Error reading file: {e}", 500

    # Directory listing
    try:
        files = sorted(os.listdir(abs_path))
    except OSError as e:
        return f"Error listing directory: {e}", 500

    html = [f"<h2>Directory: /{req_path}</h2><ul>"]

    if req_path:
        parent = os.path.dirname(req_path)
        html.append(f'<li><a href="/browse/{parent}">.. (Parent)</a></li>')

    for f in files:
        link_path = os.path.join(req_path, f).replace(os.sep, "/")
        html.append(f'<li><a href="/browse/{link_path}">{f}</a></li>')

    html.append("</ul>")
    return "".join(html)
