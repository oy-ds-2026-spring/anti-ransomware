import time
import os
from collections import deque
from watchdog.events import FileSystemEventHandler

from client import config
from client import utils
from client import rabbitmq_handler
import security
from logger import Logger


class EntropyMonitor(FileSystemEventHandler):
    def __init__(self):
        self.modification_timestamps = deque(maxlen=10)
        self.VELOCITY_THRESHOLD = 1.0
        self.file_metadata = {}
        self.SIZE_CHANGE_THRESHOLD = 0.3

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
        ext = os.path.splitext(filename)[1].lower()
        if ext in config.HIGH_ENTROPY_EXTENSIONS:
            return True
        return False

    def on_modified(self, event):
        if config.IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path
        basename = os.path.basename(filename)

        if filename.endswith(".locked") or ".tmp" in filename:
            return

        # baits detect
        if basename in config.BAITS:
            security.execute_lockdown(trigger_source="Monitor (Canary)", reason=f"Baits File [{basename}] is modified")
            rabbitmq_handler.send_msg(filename, 8.0, "BAIT_TRIGGERED")
            return

        # freq detect
        self.modification_timestamps.append(time.time())
        if self.check_modify_velocity():
            security.execute_lockdown(trigger_source="Monitor (Velocity)", reason="File modify freq exceeding 10 times/sec")
            rabbitmq_handler.send_msg(filename, 8.0, "VELOCITY_ATTACK")
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
            return

        if self._should_ignore(filename):
            return

        # sample entropy detect
        data = utils.read_sampled_data(filename)
        if not data:
            return

        entropy = utils.calculate_entropy(data)
        if entropy > 0:
            rabbitmq_handler.send_msg(filename, entropy, "MODIFY")

    def on_created(self, event):
        if config.IS_LOCKED_DOWN or event.is_directory:
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
        if config.IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path
        if self._should_ignore(filename):
            return
        rabbitmq_handler.send_msg(filename, 0, "DELETE")
