import os
import threading
import time

from recovery.database import SnapshotDB
from recovery.scheduler import snapshot_loop
from recovery.message_bus.rabbitmq_handler import start_connection, snapshot_results_listener

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
QUEUE = os.getenv("QUEUE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")
RECOVERY_QUEUE = os.getenv("RECOVERY_QUEUE", "recovery_queue")

def main():
    print("[INFO] Backup Service Starting...")

    db = SnapshotDB("snapshots.db")
    time.sleep(10)
    conn1 = start_connection("guest", "guest", host=BROKER_HOST)
    # Start listening to snapshot results
    t = threading.Thread(
        target=snapshot_results_listener,
        args=(conn1, RESULT_QUEUE, db),
        daemon=True
    )
    t.start()

    conn2 = start_connection("guest", "guest", host=BROKER_HOST)
    # start snapshot schedule
    print("[INFO] Starting Backup Snapshot Scheduler...")
    snapshot_loop(connection=conn2, queue=QUEUE)


if __name__ == "__main__":
    main()
