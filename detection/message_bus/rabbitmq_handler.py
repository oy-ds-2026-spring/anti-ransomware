import json
import uuid

import pika
import time
import os

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
RECOVER_QUEUE = os.getenv("RECOVER_QUEUE", "recover_queue")
from logger import Logger

def start_connection(username, password):
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials(username, password)
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
        except Exception as e:
            print(f"[ERROR] Failed to connect to RabbitMQ: {e}")
            time.sleep(5)
    return connection

def send_recovery_request(connection):
    channel = connection.channel()

    channel.queue_declare(queue=RECOVER_QUEUE, durable=True)

    command_id = str(uuid.uuid4())

    msg = {
        "type": "RESTORE_REQUEST",
        "command_id": command_id,
        "ts": int(time.time()),
    }

    try:
        channel.basic_publish(
            exchange="",
            routing_key=RECOVER_QUEUE,
            body=json.dumps(msg).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )

        Logger.info(f"[{time.strftime('%H:%M:%S')}] [DETECTION] Recovery request send to RabbitMQ: {msg['command_id']}")

    except Exception as e:
        Logger.error(f"[DETECTION] publish failed: {e}")

def receive_alerts():
    pass


