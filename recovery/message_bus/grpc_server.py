import uuid
from logger import Logger
import grpc
from concurrent import futures
from common import recovery_pb2
from common import recovery_pb2_grpc

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

def start_recovery(command_id: str):
    """
    Start the recovery server

    :param command_id: a unique command id representing this operation, can be generated via "command_id = str(uuid.uuid4())"
    """
    try:
        db = SnapshotDB("/data/snapshots.db")
        connection = start_connection("guest", "guest", host=BROKER_HOST)
        result = db.get_latest_success_snapshot(require_snapshot_id=True)
        restic_snapshot_id = result["restic_snapshot_id"]
        print(f"[BACKUP] The latest clean snapshot is: ", restic_snapshot_id)

        publish_request(connection, RECOVERY_QUEUE, command_id, restic_snapshot_id, type="recover")
    except Exception as e:
        print(e)
        return False, {"error": str(e)}

    return True, {"error": ""}


class RecoveryServicer(recovery_pb2_grpc.RecoveryServiceServicer):
    def TriggerRecovery(self, request, context):
        command_id = request.command_id
        if not command_id:
            command_id = str(uuid.uuid4())
            
        Logger.info(f"[gRPC] Received recovery request. Command ID: {command_id}")
        
        try:
            # Call your function!
            start_recovery(command_id)
            return recovery_pb2.RecoveryResponse(success=True, message="Recovery pipeline initiated.")
        except Exception as e:
            Logger.error(f"[gRPC] Recovery failed to start: {e}")
            return recovery_pb2.RecoveryResponse(success=False, message=str(e))
        
def serve():
    """Starts the gRPC server for the Recovery Service"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    recovery_pb2_grpc.add_RecoveryServiceServicer_to_server(RecoveryServicer(), server)
    
    server.add_insecure_port('[::]:50052') 
    server.start()
    Logger.info("Recovery gRPC server started on port 50052, waiting for commands...")
    server.wait_for_termination()



if __name__ == "__main__":
    serve()



