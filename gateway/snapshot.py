import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pika
import requests

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
EXCHANGE = os.getenv("EXCHANGE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

REQUIRED = {"finance1", "finance2", "finance3", "finance4"}


def send_request(node: str, command_id: str, timeout: float = 2.0, api: str = ""):
    url = f"http://{node}:5000/{api}"
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
        futures = [ex.submit(send_request, node, command_id, timeout, "snapshot/prepare") for node in FINANCE_NODES]

        for fut in as_completed(futures):
            node, ok, status, data = fut.result()
            results[node] = {"ok": ok, "status": status, "data": data}
            if not ok:
                all_ready = False

    return all_ready, results

def commit_all_parallel(command_id: str, timeout: float = 2.0):
    ok_all = True
    results = {}
    with ThreadPoolExecutor(max_workers=len(FINANCE_NODES)) as ex:
        futs = [ex.submit(send_request, n, command_id, timeout, "snapshot/commit") for n in FINANCE_NODES]
        for fut in as_completed(futs):
            node, ok, status, text = fut.result()
            results[node] = {"ok": ok, "status": status, "text": text}
            if not ok:
                ok_all = False
    return ok_all, results

def health_check(all_ready: bool, results: dict, type: Optional[str] = "prepare"):

    if type == "prepare":
        healthy = [n for n, r in results.items() if r.get("ok")]
        if not healthy:
            print("[ERROR] All nodes unreachable")
            return None

        preferred = "client-finance1"
        up_node = preferred if preferred in healthy else healthy[0]

        if all_ready:
            print("[INFO] ALL READY =", all_ready)
        else:
            print("[WARN] Failure in nodes detected")
            for n, r in results.items():
                tag = "OK" if r.get("ok") else "FAIL"
                print(f"[{tag}] {n} status={r.get('status')} data={r.get('data')}")

        print(f"[INFO] Picked node: {up_node}")

        return up_node

    elif type == "commit":

        if all_ready:
            print("[INFO] ALL RESUMED =", all_ready)
            return all_ready

        healthy = [n for n, r in results.items() if r.get("ok")]
        if not healthy:
            print("[ERROR] All nodes unreachable")
            return False

        print("[WARN] Failure in nodes detected")
        for n, r in results.items():
            tag = "OK" if r.get("ok") else "FAIL"
            print(f"[{tag}] {n} status={r.get('status')} data={r.get('data')}")
            return False


def send_snapshot(command_id: str, timeout: float = 10.0):
    """
    Send snapshot command to client
    returns: node, ok, status, result
    """
    all_ready, results = prepare_all_parallel(command_id)

    up_node = health_check(all_ready, results)

    if up_node is None:
        return None, False, None, {"error": "All nodes unreachable"}

    try:
        node, ok, status, data = send_request(
            node=up_node,
            command_id=command_id,
            timeout=timeout,
            api="snapshot/start",
        )
    except Exception as e:
        print(f"[ERROR] send_request exception: {e}")
        return up_node, False, "exception", {"error": str(e)}

    if ok and isinstance(data, dict):
        print("[INFO] SNAPSHOT READY")
        snap_id = data.get("snap_id") or data.get("snapshot_id")
        print(f"[INFO] SNAPSHOT ID: {snap_id}")

        print("[INFO] Resume write permission in client")
        all_ready, results = commit_all_parallel(command_id)
        if not health_check(all_ready, results, type="commit"):
            print("[WARN] retrying...")
            all_ready, results = commit_all_parallel(command_id)
            health_check(all_ready, results, type="commit")

        return node, True, status, snap_id
    else:
        print("[FAIL] SNAPSHOT FAILED")
        return node, False, status, None


