import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pika
import requests

from database import SnapshotDB

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
QUEUE = os.getenv("EXCHANGE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

REQUIRED = {"finance1","finance2","finance3","finance4"}

pending = {}

def commit_one(node: str, command_id: str, timeout: float = 2.0):
    url = f"http://{node}:5000/snapshot/commit"
    try:
        resp = requests.post(url, json={"command_id": command_id}, timeout=timeout)
        ok = (resp.status_code == 200)
        return node, ok, resp.status_code, resp.text
    except Exception as e:
        return node, False, None, str(e)

def commit_all_parallel(command_id: str, timeout: float = 2.0):
    ok_all = True
    results = {}
    with ThreadPoolExecutor(max_workers=len(FINANCE_NODES)) as ex:
        futs = [ex.submit(commit_one, n, command_id, timeout) for n in FINANCE_NODES]
        for fut in as_completed(futs):
            node, ok, status, text = fut.result()
            results[node] = {"ok": ok, "status": status, "text": text}
            if not ok:
                ok_all = False
    return ok_all, results

def snapshot_loop(connection: pika.BlockingConnection):

    channel = connection.channel()

    print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] starting")

    channel.queue_declare(queue=QUEUE, durable=True)
    while True:
        time.sleep(10)
        command_id = str(uuid.uuid4())

        msg = {
            "type": "REGULAR_SNAPSHOT",
            "command_id": command_id,
            "ts": int(time.time()),
        }

        try:
            channel.basic_publish(
                exchange="",
                routing_key=QUEUE,
                body=json.dumps(msg).encode("utf-8"),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                ),
            )

            print(f"[backup] start snapshot: {msg['command_id']}")
        except Exception as e:
            print(f"[backup] publish failed: {e}, unfreezing {command_id}")
            commit_all_parallel(command_id)

        time.sleep(60)

def results_listener(connection: pika.BlockingConnection, db: SnapshotDB):

    ch = connection.channel()

    ch.queue_declare(queue=RESULT_QUEUE, durable=True)

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

    ch.basic_consume(queue=RESULT_QUEUE, on_message_callback=on_msg, auto_ack=False)

    print("listening on", QUEUE)
    ch.start_consuming()


#
# def snapshot_scheduler():
#     print("[SNAPSHOT] scheduler started (10 min)")
#     while True:
#         time.sleep(60)  # 10 minutes
#         print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] starting")
#
#         # Phase1: pause writes on all nodes
#         all_ready = True
#         for node in FINANCE_NODES:
#             try:
#                 resp = requests.post(f"http://{node}:5000/snapshot/prepare", timeout=2)
#                 if resp.status_code != 200:
#                     all_ready = False
#                     print(f"[WARNING] Node {node} not ready.")
#             except Exception as e:
#                 all_ready = False
#                 print(f"[WARNING] Node {node} unreachable: {e}")
#
#         if all_ready:
#             print("[🍺] All nodes paused. Saving snapshot...")
#
#             timestamp = time.strftime("%Y%m%d_%H%M%S")
#             snapshot_dir = os.path.join("/data", f"snapshot_{timestamp}")
#             snapshot_dir = os.path.join("/data", timestamp)
#             os.makedirs(snapshot_dir, exist_ok=True)
#
#             for node in FINANCE_NODES:
#                 try:
#                     resp = requests.get(f"http://{node}:5000/snapshot/data", timeout=30)
#                     if resp.status_code == 200:
#                         files = resp.json()
#                         node_dir = os.path.join(snapshot_dir, node[7:])
#                         os.makedirs(node_dir, exist_ok=True)
#
#                         for rel_path, content_b64 in files.items():
#                             file_path = os.path.join(node_dir, rel_path)
#                             os.makedirs(os.path.dirname(file_path), exist_ok=True)
#                             with open(file_path, "wb") as f:
#                                 f.write(base64.b64decode(content_b64))
#                         print(f"[SNAPSHOT] Saved {len(files)} files from {node}")
#                 except Exception as e:
#                     print(f"[ERROR] Snapshot failed for {node}: {e}")
#
#             print("[🍺] Snapshot saved.")
#         else:
#             print("[WARNING] Snapshot aborted due to node failure.")
#
#         # Phase 2: Commit (Resume writes on all nodes)
#         for node in FINANCE_NODES:
#             try:
#                 requests.post(f"http://{node}:5000/snapshot/commit", timeout=2)
#             except Exception as e:
#                 print(f"[WARNING] Failed to resume {node}: {e}")
#
#         print(f"[{time.strftime('%H:%M:%S')}] Snapshot Process Finished.")