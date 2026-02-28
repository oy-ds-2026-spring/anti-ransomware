import uuid

import pika
import json
import os
import time
import sys
import grpc
import threading
from flask import Flask, jsonify

from common import lockdown_pb2, backup_pb2_grpc, backup_pb2
from common import lockdown_pb2_grpc

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import Logger

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")  # for DNS addressing
LOG_FILE = "/logs/system_state.json"  # host machine `shared_logs/` -> docker `logs/`
# ENTROPY_THRESHOLD = 7.5
FINANCE_NODES = ["finance1", "finance2", "finance3", "finance4"]

# global state, real-time maintained in memory, written to log after update
# for logging, for Dashboard
current_state = {
    "finance1": "Safe",
    "finance2": "Safe",
    "finance3": "Safe",
    "finance4": "Safe",
    "last_entropy": 0.0,
    "logs": [],
    "entropy_history": [],
    "processing_logs": [],
    "issued_commands": [],
}
# --- NEW: Dedicated Health Registry
client_health = {
    "finance1": {"health_status": "Safe", "last_entropy": 0.0},
    "finance2": {"health_status": "Safe", "last_entropy": 0.0},
    "finance3": {"health_status": "Safe", "last_entropy": 0.0},
    "finance4": {"health_status": "Safe", "last_entropy": 0.0},
}

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def get_cluster_health():
    """Endpoint for Gateway or Recovery node to ask for cluster status"""
    return jsonify(client_health), 200

def run_health_api():
    app.run(host="0.0.0.0", port=4020, debug=True, use_reloader=False)

# Helper function to update the registry cleanly
def update_health_registry(client_id, status=None, entropy=None):
    if client_id in client_health:
        if status is not None:
            client_health[client_id]["health_status"] = status
        if entropy is not None:
            client_health[client_id]["last_entropy"] = entropy

# --- Detection Profiles ---
client_profiles = {}

WINDOW_SIZE = 10
WRITE_WINDOW_SEC = 10

HIGH_ENTROPY_BASE = 7.4   # adaptive baseline
LOCKDOWN_SCORE = 6
SUSPICIOUS_SCORE = 3

# save `current_state` to shared_log
def save_state():
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "w") as f:
            json.dump(current_state, f)
    except Exception as e:
        Logger.warning(f"Dashboard update failed: {e}")


# compose new log
def log_client_status(client_id, status, entropy, message):
    global current_state

    # 1. department status
    if "finance1" in client_id:
        current_state["finance1"] = status
    elif "finance2" in client_id:
        current_state["finance2"] = status
    elif "finance3" in client_id:
        current_state["finance3"] = status
    elif "finance4" in client_id:
        current_state["finance4"] = status

    # 2. last_entropy
    current_state["last_entropy"] = entropy

    # 3. Update logs (keep only the latest 10 entries)
    timestamp = time.strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    current_state["logs"].append(log_entry)
    if len(current_state["logs"]) > 10:
        current_state["logs"].pop(0)

    # 4. Update historical trend data for the chart
    current_state["entropy_history"].append({"Time": timestamp, "Entropy": entropy})
    # Keep only the latest 50 data points to prevent chart clutter
    if len(current_state["entropy_history"]) > 50:
        current_state["entropy_history"].pop(0)

    # 5. log
    save_state()


def log_command_lock_down(client_id, timestamp):
    cmd = f"[{timestamp}] LOCK_DOWN: {client_id}"
    current_state["issued_commands"].append(cmd)
    if len(current_state["issued_commands"]) > 50:
        current_state["issued_commands"].pop(0)
    save_state()


# log which msg I'm processing, for dashboard
def log_msg_processing(client_id, file_path, entropy, event_type):
    timestamp = time.strftime("%H:%M:%S")
    log_msg = f"[{timestamp}] {client_id} | {os.path.basename(file_path)} | {event_type} | Entropy: {entropy:.2f}"
    current_state["processing_logs"].append(log_msg)
    if len(current_state["processing_logs"]) > 50:
        current_state["processing_logs"].pop(0)
    save_state()

# get client profile
def get_profile(client_id):
    return client_profiles.setdefault(client_id, {
        "entropy_window": [],
        "events": [],
        "write_burst": 0,
        "score": 0,
        "state": "Safe",
        "last_update": time.time()
    })

# adaptive thresholding logic
def adaptive_entropy_threshold(profile):
    window = profile["entropy_window"]

    if len(window) < 3:
        return HIGH_ENTROPY_BASE

    avg = sum(window) / len(window)
    return max(7.2, avg + 0.35)

def update_entropy_window(profile, entropy):
    w = profile["entropy_window"]
    w.append(entropy)

    if len(w) > WINDOW_SIZE:
        w.pop(0)

# event rate logic
def update_event_rate(profile):
    now = time.time()

    profile["events"].append(now)
    profile["events"] = [
        t for t in profile["events"]
        if now - t < WRITE_WINDOW_SEC
    ]

    return len(profile["events"])

def update_write_burst(profile, event_type):
    if event_type == "WRITE":
        profile["write_burst"] += 1
    else:
        profile["write_burst"] = max(0, profile["write_burst"] - 1)

    return profile["write_burst"]

HIGH_ENTROPY_SAFE_EXT = {".jpeg", ".gif", ".bmp", ".mp4", ".mp3", ".avi", ".mov", ".7z", ".tar"}

def is_safe_high_entropy(file_path):
    return file_path.lower().endswith(HIGH_ENTROPY_SAFE_EXT)

def calculate_score(profile, entropy, file_path, event_type):

    score = 0

    threshold = adaptive_entropy_threshold(profile)
    # entropy spike
    if entropy > threshold:
        score += 3
    # rapid file modifications
    rate = update_event_rate(profile)
    if rate > 6:
        score += 2
    # write burst behaviour
    burst = update_write_burst(profile, event_type)
    if burst > 4:
        score += 2
    # ignore safe compressed files
    if is_safe_high_entropy(file_path):
        score -= 1

    return score

# grpc trigger logic
def trigger_client_lockdown(client_id, threat_id, reason):
    client_address = f"client-{client_id}:50051"
    Logger.lock_down(f"Sending gRPC lockdown command to {client_address}...")

    with grpc.insecure_channel(client_address) as channel:
        stub = lockdown_pb2_grpc.LockdownServiceStub(channel)
        request = lockdown_pb2.LockdownRequest(
            threat_id=threat_id, timestamp=str(time.time()), reason=reason, targeted_node=client_id
        )
        try:
            # Added a short timeout so the detection engine doesn't hang if a node is down
            response = stub.TriggerLockdown(request, timeout=3)
            if response.success:
                Logger.done(f"Successfully triggered lock down on {client_address}")
            else:
                Logger.warning(
                    f"Failed to trigger lock down on {client_address}: {response.status_message}"
                )
        except grpc.RpcError as e:
            Logger.warning(f"gRPC error when contacting {client_address}: {e.details()}")

def trigger_recovery():

    channel = grpc.insecure_channel("backup-storage:50051")
    stub = backup_pb2_grpc.BackupStorageStub(channel)

    resp = stub.StartRecovery(
        backup_pb2.StartRecoveryRequest(
            command_id=str(uuid.uuid4()),
        )
    )

    print("[detection-service] response:", resp.ok, resp.message)

def handle_malware(ch, client_id, file_path, entropy):
    alert_msg = f"MALWARE DETECTED! Entropy {entropy:.2f} on {os.path.basename(file_path)}"
    Logger.ransomware(alert_msg)

    log_client_status(client_id, "Infected", entropy, alert_msg)
    update_health_registry(client_id, status="Infected", entropy=entropy)

    # send lock down command
    timestamp = time.strftime("%H:%M:%S")
    threat_id = f"RANSOM-{int(time.time())}"
    # trigger lockdown on all finance nodes
    for node in FINANCE_NODES:
        trigger_client_lockdown(node, threat_id, reason=f"High entropy threshold breached on {client_id}")
        log_command_lock_down(node, timestamp)
        if node != client_id:
            log_client_status(node, "Locked", 0, "System Lockdown Initiated")

# trigger lockdown if score breaches certain level
def update_escalation(client_id, profile, entropy, file_path, event_type, ch):

    profile["score"] += calculate_score(
        profile, entropy, file_path, event_type
    )

    # natural decay
    profile["score"] = max(0, profile["score"] - 1)

    score = profile["score"]

    if score >= LOCKDOWN_SCORE and profile["state"] != "Locked":
        profile["state"] = "Locked"
        handle_malware(ch, client_id, file_path, entropy)
        log_client_status(client_id, "Infected", entropy,
                          "High ransomware confidence")
    elif score >= SUSPICIOUS_SCORE:
        profile["state"] = "Suspicious"
        log_client_status(client_id, "Suspicious", entropy,
                          "Abnormal behaviour detected")
        update_health_registry(client_id, status="Suspicious", entropy=entropy)
    else:
        profile["state"] = "Safe"
        log_client_status(client_id, "Safe", entropy,
                          f"Normal activity: {os.path.basename(file_path)}")
        update_health_registry(client_id, status="Safe", entropy=entropy)


# msg process
def msg_callback(ch, method, properties, body):
    try:
        # msg extraction
        msg = json.loads(body)

        client_id = msg.get("client_id", "unknown")
        file_path = msg.get("file_path", "?")
        entropy = float(msg.get("entropy", 0))
        event_type = msg.get("event_type", "UNKNOWN")
        
        # test vector clock
        v_clock = msg.get("v_clock", {})

        # log current msg
        log_msg_processing(client_id, file_path, entropy, event_type)
        Logger.analyze(f" {client_id} | {file_path} | {event_type} | Entropy: {entropy:.2f}")
        
        # test vector clock
        print(f"[{client_id}] | {event_type} | {os.path.basename(file_path)} | Entropy: {entropy:.2f} | Clock: {v_clock}")

        if event_type == "LOCK_DOWN":
            status = "Locked"
            log_client_status(
                client_id, status, entropy, f"Normal activity: {os.path.basename(file_path)}"
            )
            return

        # check entropy
        # if entropy > ENTROPY_THRESHOLD:
        #     handle_malware(ch, client_id, file_path, entropy)
        # else:
        #     # Scenario B: Normal file modification
        #     # If previously 'Infected', and now a low entropy operation is received (possibly a recovered file),
        #     # the status will automatically revert to 'Safe'.
        #     status = "Safe"
        #     log_client_status(
        #         client_id, status, entropy, f"Normal activity: {os.path.basename(file_path)}"
        #     )
        profile = get_profile(client_id)

        update_entropy_window(profile, entropy)

        update_escalation(
            client_id,
            profile,
            entropy,
            file_path,
            event_type,
            ch
        )
    except Exception as e:
        Logger.warning(f"Error processing message: {e}")


def main():
    Logger.info("Detection Service Starting...")

    threading.Thread(target=run_health_api, daemon=True).start()

    #time.sleep(60)
    #trigger_recovery()

    # 1. connect to rabbitmq
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
        except pika.exceptions.AMQPConnectionError:
            Logger.warning("Waiting for RabbitMQ...")
            time.sleep(5)

    channel = connection.channel()

    # 2. listen to the queue `file_events`
    channel.queue_declare(queue="file_events")

    # 3. send commands to the queue `commands`
    # channel.queue_declare(queue="commands")

    Logger.done("Detection Engine Online. Waiting for entropy streams...")

    # 4. Start analyzing messages
    channel.basic_consume(queue="file_events", on_message_callback=msg_callback, auto_ack=True)
    channel.start_consuming()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        Logger.info("Interrupted")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
