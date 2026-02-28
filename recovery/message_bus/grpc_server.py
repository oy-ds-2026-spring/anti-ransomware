from logger import Logger
from recovery.database import SnapshotDB
from recovery.message_bus.rabbitmq_handler import publish_request
from recovery.message_bus.rabbitmq_handler import start_connection

import os
from concurrent import futures
import time
import grpc

from common import backup_pb2, backup_pb2_grpc

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
QUEUE = os.getenv("QUEUE", "regular_snapshot")
RESULT_QUEUE = os.getenv("RESULT_QUEUE", "snapshot_results")
RECOVERY_QUEUE = os.getenv("RECOVERY_QUEUE", "recovery_queue")

class BackupStorageServicer(backup_pb2_grpc.BackupStorageServicer):
    def StartRecovery(self, request, context):
        # 这里就是你原本的 start_recovery 逻辑入口（demo 先打印）
        print(f"[backup-storage] StartRecovery called: command_id={request.command_id}")

        start_recovery(request.command_id)

        return backup_pb2.StartRecoveryReply(ok=True, message="recovery started")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    backup_pb2_grpc.add_BackupStorageServicer_to_server(BackupStorageServicer(), server)

    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    print("[backup-storage] gRPC server listening on :50051")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop(0)

def start_recovery(command_id: str):
    """
    Start the recovery server

    :param command_id: a unique command id representing this operation, can be generated via "command_id = str(uuid.uuid4())"
    """
    try:
        db = SnapshotDB("snapshots.db")
        connection = start_connection("guest", "guest", host=BROKER_HOST)
        result = db.get_latest_success_snapshot(require_snapshot_id=True)
        restic_snapshot_id = result["restic_snapshot_id"]
        print(f"[BACKUP] The latest clean snapshot is: ", restic_snapshot_id)

        publish_request(connection, RECOVERY_QUEUE, command_id, restic_snapshot_id, type="recover")
    except Exception as e:
        print(e)
        return False, {"error": str(e)}

    return True, {"error": ""}


if __name__ == "__main__":
    serve()



