import threading
from watchdog.observers import Observer
import config
import routes
import utils
import grpc_server
import rabbitmq_handler
from monitor import EntropyMonitor


if __name__ == "__main__":
    print(f"[INFO] Client started on {config.CLIENT_ID}. Watching {config.MONITOR_DIR}")
    utils.fishing(config.MONITOR_DIR)
    # listen command from detection engine
    threading.Thread(target=rabbitmq_handler.lock_down_listener, daemon=True).start()
    threading.Thread(
        target=grpc_server.serve, daemon=True
    ).start()  # listen sync command from other clients
    threading.Thread(target=rabbitmq_handler.sync_listener, daemon=True).start()

    # what to do when file operation monitored
    event_handler = EntropyMonitor()

    # initialize watchdog
    # operation observed, call event_handler
    # moniter `/data`
    # also `/data`'s sub-dir
    observer = Observer()
    observer.schedule(event_handler, path=config.MONITOR_DIR, recursive=True)
    observer.start()

    # start waiting for attacker(?)
    routes.app.run(host="0.0.0.0", port=5000)
