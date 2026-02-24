import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional
import pika
from snapshot import send_snapshot

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "gateway")
QUEUE = os.getenv("SNAPSHOT_QUEUE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")

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


def snapshot_listener():
    connection = start_connection("guest", "guest")
    ch = connection.channel()

    ch.queue_declare(queue=QUEUE, durable=True)
    ch.queue_declare(queue=RESULT_QUEUE, durable=True)

    def on_msg(ch, method, props, body: bytes):
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception as e:
            print(f"[WARN] bad json message: {e}, body={body[:200]!r}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        try:
            if msg.get("type") == "REGULAR_SNAPSHOT":
                command_id = msg.get("command_id")
                if not command_id:
                    publish_result(
                        ch,
                        client_id="unknown",
                        restic_snapshot_id=None,
                        command_id=None,
                        ok=False,
                        error="missing command_id",
                    )
                else:
                    node, ok, status, result = send_snapshot(command_id)

                    if ok:
                        publish_result(
                            ch,
                            client_id=node,
                            restic_snapshot_id=result,
                            command_id=command_id,
                            ok=True,
                            error=None,
                        )
                    else:
                        publish_result(
                            ch,
                            client_id=node or "unknown",
                            restic_snapshot_id=None,
                            command_id=command_id,
                            ok=False,
                            error=str(result),
                        )
            else:
                print(f"[INFO] ignore msg type={msg.get('type')}")
        except Exception as e:
            print(f"[ERROR] handler exception: {e}")
            publish_result(
                ch,
                client_id="unknown",
                restic_snapshot_id=None,
                command_id=msg.get("command_id"),
                ok=False,
                error=f"handler exception: {e}",
            )
        finally:
            ch.basic_ack(delivery_tag=method.delivery_tag)

    ch.basic_consume(queue=QUEUE, on_message_callback=on_msg, auto_ack=False)
    print("listening on", QUEUE)
    ch.start_consuming()

def publish_result(channel, client_id: str, ok: bool, restic_snapshot_id: Optional[str] = None, command_id: Optional[str] = None, error: Optional[str] = None):
    msg = {
        "type": "SNAPSHOT_DONE" if ok else "SNAPSHOT_FAILED",
        "client_id": client_id,
        "restic_snapshot_id": restic_snapshot_id,
        "command_id": command_id,
        "ts": int(time.time()),
        "error": error,
    }
    channel.basic_publish(
        exchange="",
        routing_key=RESULT_QUEUE,
        body=json.dumps(msg).encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
        ),
    )