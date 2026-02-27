import threading
from rabbitmq_handler import snapshot_listener, recovery_listener
from backend import *


if __name__ == "__main__":
    threading.Thread(target=snapshot_listener, daemon=True).start()
    threading.Thread(target=recovery_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=9000)
