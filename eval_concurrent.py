import requests
from requests_gssapi import HTTPSPNEGOAuth
import threading
import uuid
import time

auth = HTTPSPNEGOAuth()
URL = "http://localhost:9000/finance/write"
FILENAME = "report_concurrent.txt"

# Initialize empty file
requests.post("http://localhost:9000/finance/create", json={"filename": FILENAME, "content": "Init\n", "request_id": str(uuid.uuid4())}, auth=auth)

success_count = 0
lock = threading.Lock()
NUM_THREADS = 50  # Simulating 50 concurrent clients

def send_write(thread_id):
    global success_count
    req_id = str(uuid.uuid4())
    payload = {
        "filename": FILENAME,
        "content": f"Data block from concurrent thread {thread_id}\n",
        "request_id": req_id
    }
    try:
        resp = requests.post(URL, json=payload, auth=auth)
        if resp.status_code == 200 and resp.json().get('status') == 'success':
            with lock:
                success_count += 1
    except Exception as e:
        pass

print(f"🚀 Starting Stress Test: Launching {NUM_THREADS} Concurrent Write Requests...")
start_time = time.time()

threads = []
for i in range(NUM_THREADS):
    t = threading.Thread(target=send_write, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

elapsed_time = time.time() - start_time
print(f"⏱️ Elapsed Time: {elapsed_time:.2f} seconds")
print(f"📈 Throughput (TPS): {NUM_THREADS / elapsed_time:.1f} req/s")
print(f"✅ Success Rate: {success_count}/{NUM_THREADS} ({(success_count/NUM_THREADS)*100:.1f}%)")

# docker exec -it finance-gateway python /app/eval_concurrent.py