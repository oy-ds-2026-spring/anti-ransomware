import os
import threading
import time

import pika
from flask import Flask
from scheduler import results_listener, snapshot_loop

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
app = Flask(__name__)

@app.route("/")
def index():
    return "Backup Server Coordinator"

def start_connection(username, password):
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
        except Exception as e:
            print(f"[ERROR] Failed to connect to RabbitMQ: {e}")
            time.sleep(5)
    return connection

def main():
    print("[INFO] Backup Service Starting...")

    conn1 = start_connection("guest", "guest")
    # Start listening to snapshot results
    t = threading.Thread(target=results_listener(connection=conn1), daemon=True)
    t.start()

    conn2 = start_connection("guest", "guest")
    # start snapshot schedule
    print("[INFO] Starting Backup Snapshot Scheduler...")
    snapshot_loop(connection=conn2)


if __name__ == "__main__":
    main()
