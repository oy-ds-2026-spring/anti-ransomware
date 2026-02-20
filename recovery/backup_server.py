from flask import Flask, jsonify
import threading
import os
import base64
import time
import requests

app = Flask(__name__)

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]


@app.route("/")
def index():
    return "Backup Server Coordinator"


def snapshot_scheduler():
    print("[SNAPSHOT] scheduler started (10 min)")
    while True:
        time.sleep(60)  # 10 minutes
        print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] starting")

        # Phase1: pause writes on all nodes
        all_ready = True
        for node in FINANCE_NODES:
            try:
                resp = requests.post(f"http://{node}:5000/snapshot/prepare", timeout=2)
                if resp.status_code != 200:
                    all_ready = False
                    print(f"[WARNING] Node {node} not ready.")
            except Exception as e:
                all_ready = False
                print(f"[WARNING] Node {node} unreachable: {e}")

        if all_ready:
            print("[🍺] All nodes paused. Saving snapshot...")

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            snapshot_dir = os.path.join("/data", f"snapshot_{timestamp}")
            snapshot_dir = os.path.join("/data", timestamp)
            os.makedirs(snapshot_dir, exist_ok=True)

            for node in FINANCE_NODES:
                try:
                    resp = requests.get(f"http://{node}:5000/snapshot/data", timeout=30)
                    if resp.status_code == 200:
                        files = resp.json()
                        node_dir = os.path.join(snapshot_dir, node[7:])
                        os.makedirs(node_dir, exist_ok=True)

                        for rel_path, content_b64 in files.items():
                            file_path = os.path.join(node_dir, rel_path)
                            os.makedirs(os.path.dirname(file_path), exist_ok=True)
                            with open(file_path, "wb") as f:
                                f.write(base64.b64decode(content_b64))
                        print(f"[SNAPSHOT] Saved {len(files)} files from {node}")
                except Exception as e:
                    print(f"[ERROR] Snapshot failed for {node}: {e}")

            print("[🍺] Snapshot saved.")
        else:
            print("[WARNING] Snapshot aborted due to node failure.")

        # Phase 2: Commit (Resume writes on all nodes)
        for node in FINANCE_NODES:
            try:
                requests.post(f"http://{node}:5000/snapshot/commit", timeout=2)
            except Exception as e:
                print(f"[WARNING] Failed to resume {node}: {e}")

        print(f"[{time.strftime('%H:%M:%S')}] Snapshot Process Finished.")


if __name__ == "__main__":
    threading.Thread(target=snapshot_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)
