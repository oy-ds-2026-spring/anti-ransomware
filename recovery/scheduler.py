import json
import os
import time
import uuid
import pika

from recovery.message_bus.rabbitmq_handler import publish_request

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

REQUIRED = {"finance1","finance2","finance3","finance4"}

pending = {}

def snapshot_loop(connection: pika.BlockingConnection, queue):

    print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] starting")

    while True:
        time.sleep(10)

        command_id = str(uuid.uuid4())

        publish_request(connection, queue=queue, command_id=command_id, type="regular")

        time.sleep(60)
