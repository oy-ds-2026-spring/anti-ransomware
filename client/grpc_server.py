import os
from os import path
import stat
import grpc
from concurrent import futures
from common import lockdown_pb2
from common import lockdown_pb2_grpc
import config


class LockdownServicer(lockdown_pb2_grpc.LockdownServiceServicer):
    def TriggerLockdown(self, request, context):
        if request.targeted_node != config.CLIENT_ID and request.targeted_node != "ALL":
            msg = f"Ignored. Lockdown meant for {request.targeted_node}, I am {config.CLIENT_ID}."
            print(f"[{config.CLIENT_ID}]: {msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=msg)

        print(
            f"[{config.CLIENT_ID}] received. threat_id: {request.threat_id}, reason: {request.reason}"
        )

        try:
            self.lock_directory_readonly(config.MONITOR_DIR)
            config.IS_LOCKED_DOWN = True
            success_msg = f"Directory {config.MONITOR_DIR} successfully locked (Read-Only)."
            print(f"[{config.CLIENT_ID}]: {success_msg}\n")
            return lockdown_pb2.LockdownResponse(success=True, status_message=success_msg)
        except Exception as e:
            error_msg = f"Failed to lock directory: {e}"
            print(f"[{config.CLIENT_ID}]: {error_msg}")
            return lockdown_pb2.LockdownResponse(success=False, status_message=error_msg)

    def lock_directory_readonly(path):
        # Owner: S_IREAD (Read) + S_IXUSR (Execute to enter dir)
        # Group: S_IRGRP (Read only)
        # Others: S_IROTH (Read only)
        LOCK_PERMS = stat.S_IREAD | stat.S_IXUSR | stat.S_IRGRP | stat.S_IROTH
        
        try:
            os.chmod(path, LOCK_PERMS)
            print(f"[{config.CLIENT_ID}] Folder-level lock applied instantly to {path} (Owner: rx, Group/Others: r)")
        except Exception as e:
            print(f"[{config.CLIENT_ID}] Failed to apply folder-level lock: {e}")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lockdown_pb2_grpc.add_LockdownServiceServicer_to_server(LockdownServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print(
        f"[{config.CLIENT_ID}] gRPC server started on port 50051, waiting for lockdown commands if needs..."
    )
    server.wait_for_termination()
