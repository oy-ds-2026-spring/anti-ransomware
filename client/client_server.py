import sys
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional
import time
import math
import json
import threading
import pika
import random
import stat
import csv
import uuid
import base64
from flask import Flask, jsonify
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from collections import Counter
from collections import deque
from snapshot import snapshot_listener

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client import config
from client import routes
from client import grpc_server
from client import rabbitmq_handler
from client.monitor import EntropyMonitor
from logger import Logger


if __name__ == "__main__":
    Logger.info(f"Client started on {config.CLIENT_ID}. Watching {config.MONITOR_DIR}")

    # start listening to mq and rpc calls ################################

    # listen command from detection engine
    threading.Thread(target=rabbitmq_handler.lock_down_listener, daemon=True).start()
    # listen sync command from other clients
    threading.Thread(target=rabbitmq_handler.sync_listener, daemon=True).start()

    # start gRPC server
    threading.Thread(target=grpc_server.serve, daemon=True).start()
    threading.Thread(target=snapshot_listener, daemon=True).start()

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
    routes.app.run(host="0.0.0.0", port=5000)
