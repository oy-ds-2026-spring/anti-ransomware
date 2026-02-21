import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional
import pika

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")
EXCHANGE = os.getenv("EXCHANGE", "regular_snapshot")
RESTIC_REPOSITORY = os.getenv("RESTIC_REPOSITORY", "rest:http://finance:12345678@rest-server:8000/finance1/finance1")
RESTIC_PASSWORD_FILE = os.getenv("RESTIC_PASSWORD_FILE", "/run/secrets/restic_repo_pass")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")

def publish_result(channel, client_id: str, restic_snapshot_id: str, ok: bool, command_id: str, error: Optional[str] = None):
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
            delivery_mode=2,  # 持久化（要求队列 durable）
            content_type="application/json",
        ),
    )

def snapshot_listener():
    connection = None
    while connection is None:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
        except Exception as e:
            print(f"ERROR: Failed to connect to RabbitMQ: {e}")
            time.sleep(5)

    channel = connection.channel()

    channel.exchange_declare(exchange=EXCHANGE, exchange_type="fanout", durable=True)

    queue_name = f"regular_snapshot.{CLIENT_ID}"
    channel.queue_declare(queue=queue_name, durable=True)
    channel.queue_bind(queue=queue_name, exchange=EXCHANGE)

    channel.queue_declare(queue=RESULT_QUEUE, durable=True)

    def on_msg(ch, method, properties, body):
        try:
            print(f"[{CLIENT_ID}] received command: {body.decode('utf-8')}")
            msg = json.loads(body)

            if msg.get("type") == "REGULAR_SNAPSHOT":
                snap_id = take_snapshot(
                    source_path=MONITOR_DIR,
                    repo_path=RESTIC_REPOSITORY,
                    hostname=CLIENT_ID,
                    password_file=RESTIC_PASSWORD_FILE,
                )
                publish_result(channel, CLIENT_ID, snap_id, command_id=msg.get("command_id"), ok=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            print(f"[{CLIENT_ID}] snapshot failed: {e}")
            publish_result(channel, CLIENT_ID, restic_snapshot_id="", ok=False, error=str(e))
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    channel.basic_consume(queue=queue_name, on_message_callback=on_msg, auto_ack=False)
    print(f"[{CLIENT_ID}] waiting for snapshot broadcasts...")
    channel.start_consuming()

def take_snapshot(
    source_path: str,
    repo_path: str,
    hostname: str,
    password_file: Optional[str] = None,
    password: Optional[str] = None,
    tag: str = "regular",
) -> str:
    """
    Take a local restic snapshot of `source_path` into local repo `repo_path`.
    Returns the restic command stdout (includes snapshot id lines).
    """
    if hostname is None:
        hostname = os.uname().nodename

    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = repo_path
    if password is not None:
        env["RESTIC_PASSWORD"] = password
    elif password_file is not None:
        env["RESTIC_PASSWORD_FILE"] = password_file
    else:
        raise ValueError("ERROR: Failed to take snapshot due to RESTIC_PASSWORD missing.")

    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cmd = [
        "restic", "backup", source_path,
        "--host", hostname,
        "--tag", tag,
        "--time", ts_utc,
    ]

    out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, text=True)

    snapshot_id = None
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and "snapshot_id" in obj:
            snapshot_id = obj["snapshot_id"]

    if not snapshot_id:
        raise RuntimeError("restic output did not contain snapshot_id")

    return snapshot_id