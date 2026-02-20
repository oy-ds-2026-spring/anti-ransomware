import pika
import json
import os
import time
import sys

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")  # for DNS addressing
LOG_FILE = "/logs/system_state.json"  # host machine `shared_logs/` -> docker `logs/`
ENTROPY_THRESHOLD = 7.5

# global state, real-time maintained in memory, written to log after update
# for logging, for Dashboard
current_state = {
    "finance1": "Safe",
    "finance2": "Safe",
    "finance3": "Safe",
    "finance4": "Safe",
    "last_entropy": 0.0,
    "logs": [],  # latest log
    "entropy_history": [],  # for diagram
    "processing_logs": [],
    "issued_commands": [],
}


# save `current_state` to shared_log
def save_state():
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "w") as f:
            json.dump(current_state, f)
    except Exception as e:
        print(f"⚠️ Dashboard update failed: {e}")


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


def handle_malware(ch, client_id, file_path, entropy):
    alert_msg = f"MALWARE DETECTED! Entropy {entropy:.2f} on {os.path.basename(file_path)}"
    print(f"🔴 {alert_msg}")

    log_client_status(client_id, "Infected", entropy, alert_msg)

    # send lock down command
    timestamp = time.strftime("%H:%M:%S")
    payload = {"type": "LOCK_DOWN", "client_id": client_id, "timestamp": timestamp}
    ch.basic_publish(exchange="", routing_key="commands", body=json.dumps(payload))
    print(f"🔒 [COMMAND] Sent LOCK_DOWN for {client_id}")

    log_command_lock_down(client_id, timestamp)


# msg process
def msg_callback(ch, method, properties, body):
    try:
        # msg extraction
        msg = json.loads(body)

        client_id = msg.get("client_id", "unknown")
        file_path = msg.get("file_path", "?")
        entropy = float(msg.get("entropy", 0))
        event_type = msg.get("event_type", "UNKNOWN")

        # log current msg
        log_msg_processing(client_id, file_path, entropy, event_type)
        print(f"Analyzing: {client_id} | {file_path} | {event_type} | Entropy: {entropy:.2f}")

        if event_type == "LOCK_DOWN":
            status = "Locked"
            log_client_status(
                client_id, status, entropy, f"Normal activity: {os.path.basename(file_path)}"
            )
            return

        # check entropy
        if entropy > ENTROPY_THRESHOLD:
            handle_malware(ch, client_id, file_path, entropy)
        else:
            # ✅ Scenario B: Normal file modification
            # If previously 'Infected', and now a low entropy operation is received (possibly a recovered file),
            # the status will automatically revert to 'Safe'.
            status = "Safe"
            log_client_status(
                client_id, status, entropy, f"Normal activity: {os.path.basename(file_path)}"
            )
    except Exception as e:
        print(f"❌ Error processing message: {e}")


def main():
    print("🛡️ Detection Service Starting...")

    # 1. connect to rabbitmq
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
        except pika.exceptions.AMQPConnectionError:
            print("⏳ Waiting for RabbitMQ...")
            time.sleep(5)

    channel = connection.channel()

    # 2. listen to the queue `file_events`
    channel.queue_declare(queue="file_events")

    # 3. send commands to the queue `commands`
    channel.queue_declare(queue="commands")

    print("✅ Detection Engine Online. Waiting for entropy streams...")

    # 4. Start analyzing messages
    channel.basic_consume(queue="file_events", on_message_callback=msg_callback, auto_ack=True)
    channel.start_consuming()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
