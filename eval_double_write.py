import requests
from requests_gssapi import HTTPSPNEGOAuth
import uuid
import time

auth = HTTPSPNEGOAuth()
URL_CREATE = "http://localhost:9000/finance/create"
URL_WRITE = "http://localhost:9000/finance/write"
FILENAME = "report_double_write.txt"

print("--- 1. Initializing Test File ---")
requests.post(URL_CREATE, json={"filename": FILENAME, "content": "Initial Line\n", "request_id": str(uuid.uuid4())}, auth=auth)

# Generate a static UUID to simulate a network retry/duplicate payload
req_id = str(uuid.uuid4())
payload = {
    "filename": FILENAME,
    "content": ">>> THIS IS A DUPLICATED MESSAGE <<<\n",
    "request_id": req_id
}

print(f"\n🚀 2. Sending First Request (Request ID: {req_id[:8]}...)")
r1 = requests.post(URL_WRITE, json=payload, auth=auth)
print(f"First Response: {r1.json()}")

print("\n🚀 3. Simulating Network Jitter, Sending Exact Duplicate Request...")
time.sleep(1)
r2 = requests.post(URL_WRITE, json=payload, auth=auth)
print(f"Second Response: {r2.json()}")

print("\n🔍 4. Verifying Physical Disk File Content (Duplicate text should only appear once):")
r3 = requests.get(f"http://localhost:9000/browse/{FILENAME}", auth=auth)
print("-" * 30)
# Clean up HTML tags for a clean terminal output
print(r3.text.replace('<h3>', '').replace('</h3>', '').replace('<pre>', '').replace('</pre>', ''))
print("-" * 30)

# docker exec -it finance-gateway python /app/eval_double_write.py