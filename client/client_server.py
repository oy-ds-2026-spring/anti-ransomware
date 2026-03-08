import sys
import os
import threading
import subprocess
import time
import uuid
import grpc
from watchdog.observers import Observer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client import config
from client import routes
from client import grpc_server
from client import rabbitmq_handler
from client import security
from client.monitor import EntropyMonitor
from common import recovery_pb2
from common import recovery_pb2_grpc
from logger import Logger


if __name__ == "__main__":
    Logger.done(f"Client started on {config.CLIENT_ID}. Watching {config.MONITOR_DIR}")

    # Load persisted state from previous session ########################
    security.load_state()

    # Check if system is already locked from previous incident ############
    if config.IS_LOCKED_DOWN:
        Logger.warning(f"System detected in LOCKED state. Attempting recovery...")
        try:
            # Attempt to trigger recovery pipeline
            recovery_address = "backup-storage:50052"
            with grpc.insecure_channel(recovery_address) as channel:
                stub = recovery_pb2_grpc.RecoveryServiceStub(channel)
                request = recovery_pb2.RecoveryRequest(command_id=str(uuid.uuid4()))
                
                response = stub.TriggerRecovery(request, timeout=5)
                if response.success:
                    Logger.done(f"Recovery pipeline triggered during startup: {response.message}")
                    config.IS_RECOVERING = True
                    # Wait for recovery to complete
                    time.sleep(35)  # Recovery typically takes ~30 seconds + buffer
                    config.IS_RECOVERING = False
                    # Unlock the system after recovery
                    security.execute_unlock(trigger_source="Startup (Recovery completed)", reason="System recovered from locked state")
                else:
                    Logger.warning(f"Recovery service rejected startup recovery: {response.message}")
        except grpc.RpcError as e:
            Logger.warning(f"gRPC error during startup recovery: {e.details()}")
        except Exception as e:
            Logger.warning(f"Error during startup recovery: {e}")

    # initialize kerberos ##############################################
    keytab_file = f"/keytabs/{config.CLIENT_ID}.keytab"
    for _ in range(15):
        if os.path.exists(keytab_file):
            try:
                # (cmd) `kinit`: register and get auth ticket from KDC, keytab_file as the id card.
                subprocess.run(["kinit", "-kt", keytab_file, config.CLIENT_ID], check=True)
                Logger.done("🔑 Kerberos ticket initialized.")
                break
            except Exception as e:
                Logger.warning(f"🔑 Kerberos init failed: {e}")
        time.sleep(2)

    # start listening to mq and rpc calls ################################

    # listen command from detection engine
    threading.Thread(target=rabbitmq_handler.lock_down_listener, daemon=True).start()
    # listen sync command from other clients
    threading.Thread(target=rabbitmq_handler.sync_listener, daemon=True).start()

    # start gRPC server
    threading.Thread(target=grpc_server.serve, daemon=True).start()

    # watchdog: what to do when file operation observed ###################
    event_handler = EntropyMonitor()

    # initialize watchdog
    # operation observed, call event_handler
    # moniter `/data`
    # also `/data`'s sub-dir
    observer = Observer()
    observer.schedule(event_handler, path=config.MONITOR_DIR, recursive=True)
    observer.start()

    # start flask interface ###############################################
    routes.app.run(host="0.0.0.0", port=5000, debug=True)
