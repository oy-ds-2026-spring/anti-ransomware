import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pika
import requests

from database import SnapshotDB

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
EXCHANGE = os.getenv("EXCHANGE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

REQUIRED = {"finance1","finance2","finance3","finance4"}

def prepare_one(node: str, command_id: str, timeout: float = 2.0):
    url = f"http://{node}:5000/snapshot/prepare"
    try:
        resp = requests.post(url, json={"command_id": command_id}, timeout=timeout)
        ok = (resp.status_code == 200)

        try:
            data = resp.json()
        except Exception:
            data = {"text": resp.text}
        return node, ok, resp.status_code, data
    except Exception as e:
        return node, False, None, {"error": str(e)}

def prepare_all_parallel(command_id: str, timeout: float = 2.0, max_workers: int = 4):
    results = {}
    all_ready = True

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(prepare_one, node, command_id, timeout) for node in FINANCE_NODES]

        for fut in as_completed(futures):
            node, ok, status, data = fut.result()
            results[node] = {"ok": ok, "status": status, "data": data}
            if not ok:
                all_ready = False

    return all_ready, results

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

def snapshot_loop(connection: pika.BlockingConnection, db: SnapshotDB):

    channel = connection.channel()

    print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] starting")

    channel.exchange_declare(exchange=EXCHANGE, exchange_type="fanout", durable=True)
    while True:
        command_id = str(uuid.uuid4())

        # Phase1: pause writes on all nodes
        all_ready, results = prepare_all_parallel(command_id)
        print("ALL READY =", all_ready)
        for node, r in results.items():
            if r["ok"]:
                print(f"[OK] {node} status={r['status']} data={r['data']}")
            else:
                print(f"[FAIL] {node} status={r['status']} data={r['data']}")

        if all_ready:
            msg = {
                "type": "REGULAR_SNAPSHOT",
                "command_id": command_id,
                "ts": int(time.time()),
            }

            try:
                channel.basic_publish(
                    exchange=EXCHANGE,
                    routing_key="",
                    body=json.dumps(msg).encode("utf-8"),
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                    ),
                )

                print(f"[backup] broadcast snapshot: {msg['command_id']}")
            except Exception as e:
                print(f"[backup] publish failed: {e}, unfreezing {command_id}")
                commit_all_parallel(command_id)


        else:
            print(f"[backup] failure detected, aborting snapshot")
            ok_all, commit_results = commit_all_parallel(command_id)

            for node, r in commit_results.items():
                if r["ok"]:
                    print(f"[OK] {node} status={r['status']} data={r['text']}")
                else:
                    print(f"[FAIL] {node} status={r['status']} data={r['text']}")

            if ok_all:
                print("[backup] all nodes reachable, retrying snapshot in 60s")

        time.sleep(60)

def results_listener(connection: pika.BlockingConnection, db: SnapshotDB):

    ch = connection.channel()

    ch.queue_declare(queue=RESULT_QUEUE, durable=True)

    def on_result(ch, method, properties, body):
        try:
            msg = json.loads(body)
            print(f"[backup] got result: {msg}")

            command_id = msg.get("command_id")
            client_id = msg.get("client_id")
            msg_type = msg.get("type")
            restic_snapshot_id = msg.get("restic_snapshot_id")

            if not command_id or not client_id:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Collect successful nodes
            if msg_type == "SNAPSHOT_DONE":
                pending.setdefault(command_id, {})[client_id] = msg.get("restic_snapshot_id", "")
                db.upsert_result(command_id, client_id, status="DONE", restic_snapshot_id=restic_snapshot_id)

                # If all successful, resume all write permissions
                if set(pending[command_id].keys()) >= REQUIRED:
                    print(f"[backup] all 4 snapshots done for {command_id}, committing (unfreeze)...")

                    ok_all, commit_results = commit_all_parallel(command_id)
                    print(f"[backup] commit results for {command_id}: {commit_results}")

                    if ok_all:
                        print(f"[backup] writes resumed for {command_id}")
                    else:
                        print(f"[backup] commit had failures for {command_id}, will keep state for retry/manual fix")

                    pending.pop(command_id, None)

            elif msg_type == "SNAPSHOT_FAILED":
                print(f"[backup] snapshot failed for {command_id} on {client_id}: {msg.get('error')}")
                db.upsert_result(command_id, client_id, status="FAILED", error=msg.get('error'))

                # resume write permission anyway if one failed
                ok_all, commit_results = commit_all_parallel(command_id)
                pending.pop(command_id, None)
                print(f"[backup] commit results (after failure) for {command_id}: {commit_results}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            print(f"[backup] ERROR handling result msg: {e}")
            # if error renter queue
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    ch.basic_consume(queue=RESULT_QUEUE, on_message_callback=on_result, auto_ack=False)
    print("[backup] listening snapshot_results...")
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