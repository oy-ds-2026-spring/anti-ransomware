import base64
import csv
import os
# import multiprocessing
import threading
# import stat
import time

import requests
from flasgger import Swagger
from flask import Flask, jsonify, request

# import python lib for kerberos
# whether kerberos auth is on depends on `whether flask_gssapi is installed`
# for easier dev debugging
try:
    from flask_gssapi import GSSAPI
except ImportError:
    GSSAPI = None


from client import config
from client import utils
from client.models import ReadReq, WriteReq, CreateReq, DeleteReq, Response
from client import rabbitmq_handler
from client.security import execute_unlock
from client.snapshot import start_snapshot, start_restore
from logger import Logger
from client.utils import is_duplicate_request
from client.config import krb_auth

app = Flask(__name__)
Swagger(app)

# Configure Kerberos/GSSAPI
if GSSAPI:  # if no lib is installed, it's a dev env, don't user kerberos
    app.config["GSSAPI_SPNEGO"] = True
    gss_auth = GSSAPI(app)
else:
    gss_auth = None

# close kerberos auth if dev env
def auth_required(f):
    if gss_auth:
        return gss_auth.require_auth()(f)
    return f

# unused method
# included by _async_ack_and_log(operation, filename, content, v_clock, request_id) in rabbitmq_handler.py 
def _log_and_archive(filename, operation, req_id, appended=""):
    """log locally and notify recovery service"""

    try:
        # TODO enrypt `appended` field to avoid being sniffed
        log_entry = {
            "uuid": req_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": config.CLIENT_ID,
            "filename": filename,
            "operation": operation,
            "appended": appended,
        }
        file_exists = os.path.exists(config.FILE_OPERATION_LOG)
        with open(config.FILE_OPERATION_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["uuid", "timestamp", "client_id", "filename", "operation", "appended"]
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(log_entry)

        # notify recovery service
        requests.post("http://backup-storage:8080/archive", json=log_entry, timeout=2)
        # requests.post("http://recovery-service:8080/archive", json=log_entry, timeout=2)
    except Exception as e:
        Logger.warning(f"Logging/Archive failed: {e}")


def _run_encryption(monitor_dir, client_id):
    if getattr(config, "IS_LOCKED_DOWN", False):
        Logger.warning(f"Attack blocked: {client_id} is locked down!")
        return

    for root, _, files in os.walk(monitor_dir):
        for file in files:
            filepath = os.path.join(root, file)

            # Check shared memory flag before touching the file
            if getattr(config, "IS_LOCKED_DOWN", False):
                Logger.lock_down("Lockdown activated mid-encryption. Stopping attack.")
                return

            try:
                if not os.access(root, os.W_OK):
                    Logger.lock_down(f"OS physical block: cannot write to {root}")
                    return

                # Fake encryption
                with open(filepath, "rb") as f:
                    data = f.read()

                with open(filepath, "wb") as f:
                    f.write(os.urandom(len(data)))

                os.rename(filepath, filepath + ".locked")
                Logger.encrypted(f"{file}")

                time.sleep(0.5)

            except Exception as e:
                Logger.error(f"Attack blocked by OS or lockdown: {e}")
                return


def _propagate_attack():
    peers = os.getenv("PEERS", "").split(",")
    for peer in peers:
        if not peer.strip():
            continue
        host = peer.split(":")[0]
        try:
            Logger.info(f"Propagating attack to {host}...")
            requests.get(f"http://{host}:5000/attack", params={"propagated": "true"}, auth=krb_auth, timeout=1)
        except Exception:
            pass

# simulate being attacked
@app.route("/attack", methods=["GET"])
@auth_required
def trigger_attack(**kwargs):
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
    t = threading.Thread(
        target=_run_encryption, args=(config.MONITOR_DIR, config.CLIENT_ID), daemon=True
    )
    t.start()

    # p = multiprocessing.Process(target=_run_encryption, args=(config.MONITOR_DIR, config.CLIENT_ID))
    # p.start()

    # Only propagate if this node is the origin (not triggered by another node)
    if request.args.get("propagated") != "true":
        threading.Thread(target=_propagate_attack, daemon=True).start()

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


@app.route("/snapshot/start", methods=["POST"])
def snapshot_start():
    restic_snap_id = start_snapshot()

    if restic_snap_id is None:
        return (
            jsonify(
                {"status": "error", "message": "Snapshot failed", "snapshot_id": restic_snap_id}
            ),
            500,
        )

    return jsonify({"status": "success", "snapshot_id": restic_snap_id}), 200


@app.route("/health", methods=["GET"])
def test_health():
    """
    Test the health of the detection service.
    ---
    tags:
      - Health
    responses:
      200:
        description: Returns the health status of the detection service.
    """
    try:
        resp = requests.get("http://detection-service:4020/health", timeout=2, auth=krb_auth)
        return resp.json(), resp.status_code
    except Exception as e:
        return {"error": str(e)}, 500

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
    return jsonify({"status": "resumed"}), 200

@app.route("/snapshot/recover", methods=["POST"])
def snapshot_recover():
    config.IS_RECOVERING = True
    execute_unlock(trigger_source="Recovery Engine", reason="OS write permission for Restic")
    
    try:
        print("[INFO] Received snapshot recover request.")
        data = request.get_json(silent=True) or {}
        snapshot_id = data.get("clean_snapshot_id")
        print("[INFO] Recovering to snapshot: ", snapshot_id)

        if not snapshot_id:
            return jsonify({"ok": False, "error": "missing snapshot_id"}), 400

        ok, message =  start_restore(snapshot_id=snapshot_id)
        if ok:
            return jsonify({"status": "successful"}), 200
        else:
            return jsonify({"status": "error", "message": message}), 500
    
    finally:
        config.IS_RECOVERING = False
        print("[INFO] Recovery shield deactivated. Node ready for sync.")


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
# `kwargs` to solve the arg issue after adding kerberos auth
@app.route("/read", methods=["POST"])
@auth_required
def read_file(**kwargs):
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
@auth_required
def create_file(**kwargs):
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
    
    # check double-write
    json_data = request.get_json() or {}
    req_id = json_data.get("request_id", None) # Uuid generated by gateway
    if req_id and is_duplicate_request(json_data.pop("request_id", None)): # pop to clean data for model `CreateReq`
        return jsonify(Response(status="success", message="Request already processed (idempotent)").to_dict())

    try:
        req = CreateReq(**json_data)
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    try:
        utils.local_create(req.filename, req.content)

        current_clock = utils.increment_clock(req.filename)
        # broadcast to others via RabbitMQ
        rabbitmq_handler.broadcast_sync("CREATE", req.filename, content=req.content, v_clock=current_clock, request_id=req_id)

        # _log_and_archive(req.filename, "CREATE", req_id, req.content)

        return jsonify(Response(status="success", message="File created").to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# work only for primary node
# param: filename and content to be appended(append only)
# return: file content after modification
@app.route("/write", methods=["POST"])
@auth_required
def write_file(**kwargs):
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

    # check double-write
    json_data = request.get_json() or {}
    req_id = json_data.get("request_id", None)
    if req_id and is_duplicate_request(json_data.pop("request_id", None)): # pop to clean data for model
        return jsonify(Response(status="success", message="Request already processed (idempotent)").to_dict())

    try:
        req = WriteReq(**json_data)
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename and content are required").to_dict()), 400

    try:
        new_content = utils.local_write(req.filename, req.content)

        current_clock = utils.increment_clock(req.filename)
        # broadcast to others via RabbitMQ # with clock
        rabbitmq_handler.broadcast_sync("WRITE", req.filename, content=req.content, v_clock=current_clock, request_id=req_id)

        # _log_and_archive(req.filename, "WRITE", req_id, req.content)

        return jsonify(Response(status="success", content=new_content).to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# work only for primary node
# param: filename
# return: success status
@app.route("/delete", methods=["POST"])
@auth_required
def delete_file(**kwargs):
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

    # check double-write
    json_data = request.get_json() or {}
    req_id = json_data.get("request_id", None)
    if req_id and is_duplicate_request(json_data.pop("request_id", None)): # pop to clean data for model
        return jsonify(Response(status="success", message="Request already processed (idempotent)").to_dict())

    try:
        req = DeleteReq(**json_data)
    except (TypeError, AttributeError):
        return jsonify(Response(error="Filename is required").to_dict()), 400

    filepath = os.path.join(config.MONITOR_DIR, req.filename)
    try:
        if not os.path.exists(filepath):
            return jsonify(Response(error="File not found").to_dict()), 404

        utils.local_delete(req.filename)

        current_clock = utils.increment_clock(req.filename)
        # broadcast to others via RabbitMQ # with clock
        rabbitmq_handler.broadcast_sync("DELETE", req.filename, v_clock=current_clock, request_id=req_id)

        # _log_and_archive(req.filename, "DELETE", req_id, "")

        return jsonify(Response(status="success", message="File deleted").to_dict())
    except Exception as e:
        return jsonify(Response(status="error", message=str(e)).to_dict()), 500


# Simple file browser to view /data structure and content
@app.route("/browse", defaults={"req_path": ""})
@app.route("/browse/<path:req_path>")
@auth_required
def browse_fs(req_path, **kwargs):
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
        return f"[{config.CLIENT_ID}] Forbidden", 403

    if not os.path.exists(abs_path):
        return f"[{config.CLIENT_ID}] Not Found", 404

    if os.path.isfile(abs_path):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return f"<h3>File: {req_path}</h3><pre>{content}</pre>"
        except Exception as e:
            return f"[{config.CLIENT_ID}] Error reading file: {e}", 500

    # Directory listing
    try:
        files = sorted(os.listdir(abs_path))
    except OSError as e:
        return f"[{config.CLIENT_ID}] Error listing directory: {e}", 500

    html = [f"<h2>Directory: /{req_path}</h2><ul>"]

    if req_path:
        parent = os.path.dirname(req_path)
        html.append(f'<li><a href="/browse/{parent}">.. (Parent)</a></li>')

    for f in files:
        link_path = os.path.join(req_path, f).replace(os.sep, "/")
        html.append(f'<li><a href="/browse/{link_path}">{f}</a></li>')

    html.append("</ul>")
    return "".join(html)
