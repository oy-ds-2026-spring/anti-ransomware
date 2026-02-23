import threading
from receiver import snapshot_listener
from backend import *


if __name__ == "__main__":
    # Initialize Kerberos Ticket
    keytab_file = "/keytabs/gateway.keytab"
    for _ in range(15):
        if os.path.exists(keytab_file):
            try:
                subprocess.run(["kinit", "-kt", keytab_file, "gateway"], check=True)
                print("Kerberos initialized successfully.")
                break
            except Exception as e:
                print(f"Warning: Kerberos init failed: {e}")
        time.sleep(2)

    threading.Thread(target=snapshot_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=9000)
