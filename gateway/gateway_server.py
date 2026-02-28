import subprocess
import threading
import time

from gateway.rabbitmq_handler import snapshot_listener, recovery_listener
from gateway.routes import *
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import Logger


if __name__ == "__main__":
    # initialize kerberos ticket ######################################
    # gateway does not require http auth from user, it only needs the key
    # to visit clients.
    keytab_file = "/keytabs/gateway.keytab"
    for _ in range(15):
        if os.path.exists(keytab_file):
            try:
                subprocess.run(["kinit", "-kt", keytab_file, "gateway"], check=True)
                Logger.done("🔑 Kerberos initialized.")
                break
            except Exception as e:
                Logger.warning(f"Warning: 🔑 Kerberos init failed: {e}")
        time.sleep(2)

    threading.Thread(target=snapshot_listener, daemon=True).start()
    threading.Thread(target=recovery_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=9000)
