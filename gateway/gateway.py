import threading
from rabbitmq_handler import snapshot_listener
from backend import *


if __name__ == "__main__":
    threading.Thread(target=snapshot_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=9000)
