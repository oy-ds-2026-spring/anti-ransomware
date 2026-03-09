import json
import os
import sys
import time
import traceback
from typing import Optional

import pika

from gateway.snapshot import send_recovery, send_snapshot

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "gateway")
QUEUE = os.getenv("SNAPSHOT_QUEUE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")
RECOVERY_QUEUE = os.getenv("RECOVERY_QUEUE", "recovery_queue")
RECOVERY_STARTED = False


def start_connection(username, password):
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials(username, password)
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials))
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
                        type="regular",
                    )
                else:
                    node, ok, ok, result = send_snapshot(command_id)

                    if ok:
                        publish_result(
                            ch,
                            client_id=node,
                            restic_snapshot_id=result,
                            command_id=command_id,
                            ok=True,
                            error=None,
                            type="regular",
                        )
                    else:
                        publish_result(
                            ch,
                            client_id=node or "unknown",
                            restic_snapshot_id=None,
                            command_id=command_id,
                            ok=False,
                            error=str(result),
                            type="regular",
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


def recovery_listener():
    connection = start_connection("guest", "guest")

    ch = connection.channel()

    ch.queue_declare(queue=RECOVERY_QUEUE, durable=True)

    def on_msg(ch, method, props, body: bytes):
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception as e:
            print(f"[WARN] bad json message: {e}, body={body[:200]!r}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        try:
            if msg.get("type") == "RESTORE_REQUEST":
                global RECOVERY_STARTED
                #
                # print("RECOVERY STATUS############")
                # print(RECOVERY_STARTED)
                # print("############")

                if RECOVERY_STARTED:
                    # print("recovery process already started.")
                    return False, None, None

                RECOVERY_STARTED = True
                print("[INFO] got msg=", msg.get("type"))
                clean_snapshot_id = msg.get("snapshot_id")
                command_id = msg.get("command_id")
                print(f"[INFO] Got message: {msg.get('type')}, command_id={msg.get('command_id')}")
                print("[INFO] Sending Snapshot restore request...")
                ok, successful_nodes, message = send_recovery(command_id, clean_snapshot_id)
            else:
                print(f"[INFO] ignore msg type={msg.get('type')}")
        except Exception as e:
            traceback.print_exc()
            print(f"[ERROR] handler exception: {e}")
        finally:
            ch.basic_ack(delivery_tag=method.delivery_tag)

    ch.basic_consume(queue=RECOVERY_QUEUE, on_message_callback=on_msg, auto_ack=False)
    print("listening on", RECOVERY_QUEUE)
    ch.start_consuming()


def publish_result(
    channel,
    ok: bool,
    client_id: Optional[str] = None,
    restic_snapshot_id: Optional[str] = None,
    command_id: Optional[str] = None,
    error: Optional[str] = None,
    type: str = "regular",
):
    if type == "regular":
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
    elif type == "recover":

        msg = {
            "type": "RESTORE_SUCCESS" if ok else "RESTORE_FAILED",
            "command_id": command_id,
            "client_id": client_id,
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
