import os
from os import path
import stat
import grpc
from concurrent import futures

from common import lockdown_pb2
from common import lockdown_pb2_grpc
from client import config
from client.security import execute_lockdown


class LockdownServicer(lockdown_pb2_grpc.LockdownServiceServicer):
    def TriggerLockdown(self, request, context):
        if request.targeted_node != config.CLIENT_ID and request.targeted_node != "ALL":
            msg = f"Ignored. Lockdown meant for {request.targeted_node}, I am {config.CLIENT_ID}."
            print(f"[{config.CLIENT_ID}]: {msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=msg)

        print(f"[{config.CLIENT_ID}] gRPC received. threat_id: {request.threat_id}, reason: {request.reason}")

        success, msg = execute_lockdown(
            trigger_source="gRPC (Detection Service)", 
            reason=request.reason
        )

        return lockdown_pb2.LockdownResponse(success=success, status_message=msg)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lockdown_pb2_grpc.add_LockdownServiceServicer_to_server(LockdownServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print(
        f"[{config.CLIENT_ID}] gRPC server started on port 50051, waiting for lockdown commands if needs..."
    )
    server.wait_for_termination()
