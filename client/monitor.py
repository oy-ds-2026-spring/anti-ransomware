import time
import os
import threading
import uuid
import grpc
from collections import deque
from watchdog.events import FileSystemEventHandler

from client import config
from client import utils
from client import rabbitmq_handler
from client import security
from common import recovery_pb2
from common import recovery_pb2_grpc
from logger import Logger


class EntropyMonitor(FileSystemEventHandler):
    def __init__(self):
        self.modification_timestamps = deque(maxlen=10)
        self.VELOCITY_THRESHOLD = 1.0
        self.file_metadata = {}
        self.SIZE_CHANGE_THRESHOLD = 0.3
        self.recovery_triggered = False  # Ensure recovery is only triggered once per lockdown
        # Reset recovery flag if system recovered at startup
        if not config.IS_LOCKED_DOWN and not getattr(config, "IS_RECOVERING", False):
            self.recovery_triggered = False
        Logger.info("EntropyMonitor initialized")

    def check_modify_velocity(self):
        if len(self.modification_timestamps) == 10:
            time_diff = self.modification_timestamps[-1] - self.modification_timestamps[0]
            if time_diff < self.VELOCITY_THRESHOLD:
                return True
        return False

    def check_size_change(self, filepath, current_size):
        if filepath in self.file_metadata:
            old_size = self.file_metadata[filepath]["size"]
            if old_size > 0:
                change_ratio = abs(current_size - old_size) / old_size
                if change_ratio >= self.SIZE_CHANGE_THRESHOLD:
                    return True, change_ratio
        return False, 0

    def _should_ignore(self, filename):
        if filename.endswith(".locked") or ".tmp" in filename:
            return True
        if "eval_concurrent.txt" in filename:
            return True
        ext = os.path.splitext(filename)[1].lower()
        if ext in config.HIGH_ENTROPY_EXTENSIONS:
            return True
        return False

    def trigger_recovery_pipeline(self):
        """Call recovery service via gRPC to initiate recovery pipeline"""
        try:
            recovery_address = "backup-storage:50052"
            Logger.warning(f"Triggering recovery pipeline via gRPC to {recovery_address}...")
            
            with grpc.insecure_channel(recovery_address) as channel:
                stub = recovery_pb2_grpc.RecoveryServiceStub(channel)
                request = recovery_pb2.RecoveryRequest(command_id=str(uuid.uuid4()))
                
                response = stub.TriggerRecovery(request, timeout=5)
                if response.success:
                    Logger.done(f"Recovery pipeline triggered: {response.message}")
                else:
                    Logger.warning(f"Recovery service rejected: {response.message}")
        except grpc.RpcError as e:
            Logger.warning(f"gRPC error triggering recovery: {e.details()}")
        except Exception as e:
            Logger.warning(f"Error triggering recovery pipeline: {e}")


    def on_modified(self, event):
        # Reset recovery flag if recovery has completed
        if self.recovery_triggered and not getattr(config, "IS_RECOVERING", False) and not config.IS_LOCKED_DOWN:
            self.reset_recovery_flag()
        
        if config.IS_LOCKED_DOWN or getattr(config, "IS_RECOVERING", False) or event.is_directory: 
            return
        filename = event.src_path
        
        if self._should_ignore(filename):
            return
        
        basename = os.path.basename(filename)

        if filename.endswith(".locked") or ".tmp" in filename:
            return

        # baits detect
        if basename in config.BAITS:
            security.execute_lockdown(trigger_source="Monitor (Canary)", reason=f"Baits File [{basename}] is modified")
            rabbitmq_handler.send_msg(filename, 8.0, "BAIT_TRIGGERED")
            # Trigger recovery pipeline
            if not self.recovery_triggered:
                self.recovery_triggered = True
                threading.Thread(target=self.trigger_recovery_pipeline, daemon=True).start()
            return

        # freq detect
        self.modification_timestamps.append(time.time())
        if self.check_modify_velocity():
            security.execute_lockdown(trigger_source="Monitor (Velocity)", reason="File modify freq exceeding 10 times/sec")
            rabbitmq_handler.send_msg(filename, 8.0, "VELOCITY_ATTACK")
            # Trigger recovery pipeline
            if not self.recovery_triggered:
                self.recovery_triggered = True
                threading.Thread(target=self.trigger_recovery_pipeline, daemon=True).start()
            return

        # file size detect
        try:
            current_size = os.path.getsize(filename)
            is_suspicious_size, ratio = self.check_size_change(filename, current_size)
            self.file_metadata[filename] = {"size": current_size}
            if is_suspicious_size:
                Logger.warning(f"Size Anomaly: {basename} changed by {ratio*100:.1f}%")
                rabbitmq_handler.send_msg(filename, 0, "SIZE_ANOMALY")
        except OSError:
            pass

        # header detect
        ext = os.path.splitext(filename)[1].lower()
        if ext in config.PROPER_HEADS:
            if utils.is_header_modified(filename, ext):
                security.execute_lockdown(trigger_source="Monitor (Magic Bytes)", reason=f"Detected {ext} file header modified")
                rabbitmq_handler.send_msg(filename, 8.0, "MODIFY")
                # Trigger recovery pipeline
                if not self.recovery_triggered:
                    self.recovery_triggered = True
                    threading.Thread(target=self.trigger_recovery_pipeline, daemon=True).start()
            return

        # sample entropy detect
        data = utils.read_sampled_data(filename)
        if not data:
            return

        entropy = utils.calculate_entropy(data)
        if entropy > 0:
            rabbitmq_handler.send_msg(filename, entropy, "MODIFY")

    def on_created(self, event):
        if config.IS_LOCKED_DOWN or getattr(config, "IS_RECOVERING", False) or event.is_directory:
            return
        filename = event.src_path
        if self._should_ignore(filename):
            return

        time.sleep(0.05)
        data = utils.read_sampled_data(filename)
        if not data:
            return

        entropy = utils.calculate_entropy(data)
        if entropy > 0:
            rabbitmq_handler.send_msg(filename, entropy, "CREATE")

    def on_deleted(self, event):
        if config.IS_LOCKED_DOWN or getattr(config, "IS_RECOVERING", False) or event.is_directory:
            return
        filename = event.src_path
        if self._should_ignore(filename):
            return
        rabbitmq_handler.send_msg(filename, 0, "DELETE")

    def reset_recovery_flag(self):
        """Reset recovery triggered flag - called after recovery completes"""
        self.recovery_triggered = False
        Logger.info("Recovery flag reset. System ready for new threat detection.")
