import os
import threading

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")
FILE_OPERATION_LOG = "/logs/file_operation_log.csv"

IS_LOCKED_DOWN = False
WRITE_PERMISSION = threading.Event()
WRITE_PERMISSION.set()  # initially allowed

BAITS = [
    "!000_admin_passwords.txt",  # forward traverse
    "~system_config_backup.ini",  # special char/system file
    "zzz_do_not_delete.dat",  # reverse traverse
]

NUM_BLOCKS = 4
BLOCK_SIZE = 4096

HIGH_ENTROPY_EXTENSIONS = {".jpeg", ".gif", ".bmp", ".mp4", ".mp3", ".avi", ".mov", ".7z", ".tar"}

PROPER_HEADS = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG",
    ".zip": b"PK\x03\x04",
    ".jpg": b"\xff\xd8\xff",
    ".rar": b"Rar!\x1a\x07",
    ".gz": b"\x1f\x8b",
}

# print(f"[INIT] State module loaded. Client ID: {CLIENT_ID}")
