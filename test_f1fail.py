import requests
import time

GATEWAY_URL = "http://localhost:9000/finance"
requests.post(f"{GATEWAY_URL}/create", json={"filename": "failover.txt", "content": "Init\n"})

print("🚀 Starting continuous writes. Go ahead and STOP client-finance1 now!")
for i in range(1, 15):
    try:
        resp = requests.post(f"{GATEWAY_URL}/write", json={"filename": "failover.txt", "content": f"Msg {i}\n"}, timeout=5)
        print(f"✅ Write {i} success. HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ Write {i} failed: {e}")
    time.sleep(1)