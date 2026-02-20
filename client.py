import os
import time
import math
import json
import threading
import pika
import random
from flask import Flask, jsonify
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter
from collections import deque

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")

IS_LOCKED_DOWN = False

BAITS = [
    "!000_admin_passwords.txt",  # forward traverse
    "~system_config_backup.ini", # special char/system file
    "zzz_do_not_delete.dat"      # reverse traverse
]

# generate some baits file, if these files are modified meaning the file is being attack
def fishing(monitor_dir):
    # spread baits
    print(f"[Info] Bait files deployed at: {monitor_dir}")
    for bait_name in BAITS:
        filepath = os.path.join(monitor_dir, bait_name)
        content = b"ADMIN_ROOT_PASSWORD=Secret2026\nDB_IP=192.168.1.1\n"
        try:
            with open(filepath, "wb") as f:
                f.write(content)
        except Exception as e:
            print(f"[Error] Deploy bait file failed, {bait_name}: {e}")


# send msg to RabbitMQ
def send_msg(file_path, entropy, event_type):
    try:
        # init short connection for every sending
        credentials = pika.PlainCredentials("guest", "guest")
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
        )
        channel = connection.channel()

        channel.queue_declare(queue="file_events")

        payload = {
            "client_id": CLIENT_ID,
            "file_path": file_path,
            "entropy": entropy,
            "event_type": event_type,
            "timestamp": time.time(),
        }

        channel.basic_publish(exchange="", routing_key="file_events", body=json.dumps(payload))
        print(
            f"[SENT] {file_path} | Entropy: {entropy:.2f} | Event: {event_type}"
        )  # Add event type to output
        connection.close()
    except Exception as e:
        print(f"[Error] RabbitMQ Error: {e}")


def calculate_entropy(data):
    if not data:
        return 0

    # shannon entropy, to see how 'random' a file is
    entropy = 0
    total_len = len(data)

    counts = Counter(data)

    for count in counts.values():
        p_x = count / total_len
        if p_x > 0:
            entropy += -p_x * math.log(p_x, 2)

    return entropy

NUM_BLOCKS = 4
BLOCK_SIZE = 4096

HIGH_ENTROPY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', 
    '.mp4', '.mp3', '.avi', '.mov',
    '.zip', '.gz', '.rar', '.7z', '.tar',
    '.pdf'
}

PROPER_HEADS = {
    '.pdf': b'%PDF',
    '.png': b'\x89PNG',
    '.zip': b'PK\x03\x04',
    '.jpg': b'\xff\xd8\xff',
    '.rar': b'Rar!\x1a\x07',
    '.gz':  b'\x1f\x8b'
}

def is_header_modified(filepath, ext):
    # header of some file types are fixed
    # check header of specific file type
    # if the header is not the expected header, the file is modified
    expected_header = PROPER_HEADS.get(ext)
    if not expected_header:
        return False

    try:
        with open(filepath, "rb") as f:
            header = f.read(len(expected_header))
            if header == expected_header:
                return False
            else:
                return True
    except Exception:
        return False

def read_sampled_data(filepath):
    # will check 4 blocks of 4096 size of the file
    # random sample read, check start, mid start, mid end, end
    # combating intermittent encryption
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return b""

        with open(filepath, "rb") as f:
            # if file is smaller than sample, read all
            if file_size <= BLOCK_SIZE * NUM_BLOCKS:
                return f.read()

            sampled_data = bytearray()
            region_size = file_size // NUM_BLOCKS

            for i in range(NUM_BLOCKS):
                # allocate start and end
                region_start = i * region_size
                max_offset = max(region_start, region_start + region_size - BLOCK_SIZE)
                
                # apply random read
                offset = random.randint(region_start, max_offset)
                
                f.seek(offset)  # move to random place
                sampled_data.extend(f.read(BLOCK_SIZE))

            return bytes(sampled_data)
    except Exception as e:
        print(f"[Error] Failed to read {filepath} | Error: {e}")
        return b""

class EntropyMonitor(FileSystemEventHandler):
    def __init__(self):
        # note the time when the file is modified
        self.modification_timestamps = deque(maxlen=10) 
        self.VELOCITY_THRESHOLD = 1.0 # sus behavior: 10 modifications in 1s
        
    def check_modify_velocity(self):
        if len(self.modification_timestamps) == 10:
            time_diff = self.modification_timestamps[-1] - self.modification_timestamps[0]
            if time_diff < self.VELOCITY_THRESHOLD:
                return True
        return False
        
    def _should_ignore(self, filename):
        # ignore files that is locked and temp files
        if filename.endswith(".locked") or ".tmp" in filename:
            return True
            
        # ignore high entropy file types
        ext = os.path.splitext(filename)[1].lower()
        if ext in HIGH_ENTROPY_EXTENSIONS:
            return True
            
        return False

    def on_modified(self, event):
        # only monitor file
        if IS_LOCKED_DOWN or event.is_directory:
            return  # don't report when lock_down
        filename = event.src_path
        basename = os.path.basename(filename)
        
        if basename in BAITS:
            print(f"[Warning] Confirmed Attack: Baits File [{basename}] is modified.")
            # TODO: 这里算local edge monitoring么，直接lockdown本地
            IS_LOCKED_DOWN = True 
            
            send_msg(filename, 8.0, "CANARY_TRIGGERED") 
            return
        
        self.modification_timestamps.append(time.time())
        
        if self.check_velocity():
            print(f"[Warning] Possible Attack: File modify freq exceeding 10 times/sec.")
            send_msg(filename, 8.0, "VELOCITY_ATTACK")
            return

        if self._should_ignore(filename):
            return
        
        ext = os.path.splitext(filename)[1].lower()
        
        # check headers
        if ext in PROPER_HEADS:
            if is_header_modified(filename, ext):
                # skip entropy calc since this file is confirm modified
                print(f"[Warning] Confirmed Attack: Detected {ext} file header is modified: {filename}")
                send_msg(filename, 8.0, "MODIFY") # red flag this file
            return
        
        data = read_sampled_data(filename) # use random sample check
        if not data:
            return
        
        # only report if entropy is high
        entropy = calculate_entropy(data)
        if entropy > 0:
            send_msg(filename, entropy, "MODIFY")


    def on_created(self, event):
        if IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path

        if self._should_ignore(filename):
            return
        
        time.sleep(0.05) # wait for file writing done
        
        # calculate entropy for newly created files        
        # apply random sample check
        data = read_sampled_data(filename)
        if not data:
            return
            
        entropy = calculate_entropy(data)
        if entropy > 0:
            send_msg(filename, entropy, "CREATE")

    def on_deleted(self, event):
        if IS_LOCKED_DOWN or event.is_directory:
            return
        filename = event.src_path

        if self._should_ignore(filename):
            return

        # entropy cannot be calc on deletion
        # only report the delete event
        send_msg(filename, 0, "DELETE")


# listen to RabbitMQ
def lock_down_listener():
    global IS_LOCKED_DOWN
    while True:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.queue_declare(queue="commands")

            def callback(ch, method, properties, body):
                global IS_LOCKED_DOWN
                msg = json.loads(body)

                IS_LOCKED_DOWN = True
                print(f"[LOCK_DOWN] Command received! Isolating {CLIENT_ID}...")
                # report ok
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")

            channel.basic_consume(queue="commands", on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            time.sleep(5)


app = Flask(__name__)


# simulate being attacked
@app.route("/attack", methods=["POST"])
def trigger_attack():
    def run_encryption():
        print(f"[RANSOMWARE] Attack started on {CLIENT_ID}...")
        for root, _, files in os.walk(MONITOR_DIR):
            for file in files:
                if file.endswith(".locked"):
                    continue

                filepath = os.path.join(root, file)
                try:
                    # read original file
                    with open(filepath, "rb") as f:
                        data = f.read()

                    # generate high-entropy random data
                    # (because real AES encryption is of high overhead)
                    encrypted = os.urandom(len(data))
                    with open(filepath, "wb") as f:
                        f.write(encrypted)

                    # rename
                    new_filepath = filepath + ".locked"
                    os.rename(filepath, new_filepath)

                    print(f"Encrypted: {file}")

                    # slow down so watchdog does not miss anything
                    # simulating ransomware one by one
                    time.sleep(0.5)

                except Exception as e:
                    print(f"Failed to encrypt {file}: {e}")

    # new a thread to encrypt
    threading.Thread(target=run_encryption).start()
    return jsonify({"status": "infected", "target": CLIENT_ID})


# simulate normal operation
@app.route("/normal", methods=["POST"])
def trigger_normal():
    global IS_LOCKED_DOWN
    IS_LOCKED_DOWN = False

    target_file = None
    for root, _, files in os.walk(MONITOR_DIR):
        if files:
            target_file = os.path.join(root, files[0])
            break

    if target_file:
        try:
            with open(target_file, "a") as f:
                f.write("\nhello world")
            print(f"[NORMAL] Modified {target_file}")
            return jsonify({"status": "success", "file": target_file})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "no_files_found"}), 404


if __name__ == "__main__":
    print(f"Client started on {CLIENT_ID}. Watching {MONITOR_DIR}")
    # deploy decoy files
    fishing(MONITOR_DIR)
    threading.Thread(target=lock_down_listener, daemon=True).start()

    # what to do when file operation monitored
    event_handler = EntropyMonitor()

    # initialize watchdog
    # operation observed, call event_handler
    # moniter `/data`
    # also `/data`'s sub-dir
    observer = Observer()
    observer.schedule(event_handler, path=MONITOR_DIR, recursive=True)
    observer.start()

    # start waiting for attacker(?)
    app.run(host="0.0.0.0", port=5000)
