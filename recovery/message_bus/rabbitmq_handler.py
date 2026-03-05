from typing import Optional

import json
import pika
import time

from logger import Logger
from recovery.database import SnapshotDB


def start_connection(username, password, host):
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials(username, password)
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=host, credentials=credentials)
            )
        except Exception as e:
            print(f"[ERROR] Failed to connect to RabbitMQ: {e}")
            time.sleep(5)
    return connection


def snapshot_results_listener(connection: pika.BlockingConnection, queue: str, db: SnapshotDB):
    ch = connection.channel()

    ch.queue_declare(queue=queue, durable=True)

    def on_msg(ch, method, props, body: bytes):
        msg = json.loads(body)

        if msg.get("type") == "SNAPSHOT_DONE":
            client_id = msg.get("client_id")
            command_id = msg.get("command_id")
            restic_snapshot_id = msg.get("restic_snapshot_id")
            print("[INFO] Got message: ", msg.get("type"))
            print("[INFO] Saving Result to DB.")
            db.upsert_result(command_id, client_id, status="DONE", restic_snapshot_id=restic_snapshot_id)

        else:
            print("[INFO] Got message: ", msg.get("type"))
            client_id = msg.get("client_id")
            command_id = msg.get("command_id")
            error = msg.get("error")
            db.upsert_result(command_id, client_id, status="FAILED", error=error)

        ch.basic_ack(delivery_tag=method.delivery_tag)

    ch.basic_consume(queue=queue, on_message_callback=on_msg, auto_ack=False)

    print("listening on", queue)
    ch.start_consuming()


# def recovery_listener(connection: pika.BlockingConnection, queue: str, db: SnapshotDB):
#     ch = connection.channel()
#
#     def on_msg(ch, method, props, body: bytes):
#         msg = json.loads(body)
#
#         if msg.get("type") == "RESTORE_REQUEST":
#             command_id = msg.get("command_id")
#             Logger.info(f"[BACKUP] Got message: {msg.get('type')}")
#
#             _, client_id, restic_snapshot_id, created_ts = db.get_latest_success_snapshot(require_snapshot_id=True)
#             Logger.info(f"[BACKUP] The latest clean snapshot is: {restic_snapshot_id}")
#
#             publish_request(connection, queue, command_id, restic_snapshot_id, type="recover")
#
#         ch.basic_ack(delivery_tag=method.delivery_tag)
#
#     ch.basic_consume(queue=queue, on_message_callback=on_msg, auto_ack=False)
#
#     print("listening on", queue)
#     ch.start_consuming()


def publish_request(
        connection: pika.BlockingConnection,
        queue: str,
        command_id: str,
        snapshot_id: Optional[str] = None,
        type: Optional[str] = "regular"
):
    channel = connection.channel()
    channel.queue_declare(queue=queue, durable=True)

    if type == "regular":
        msg = {
            "type": "REGULAR_SNAPSHOT",
            "command_id": command_id,
            "ts": int(time.time()),
        }

        Logger.info(f"[backup] start snapshot: {msg['command_id']}")

    elif type == "recover":
        msg = {
            "type": "RESTORE_REQUEST",
            "command_id": command_id,
            "snapshot_id": snapshot_id,
            "ts": int(time.time()),
        }

        Logger.info(f"[backup] sending restore request: {msg['command_id']}")

    else:
        raise Exception(f"[backup] Unknown type: {type}")

    try:
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(msg).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )


    except Exception as e:
        Logger.error(f"[backup] publish failed: {e}")


