import requests
import uuid

GATEWAY_URL = "http://localhost:9000/finance"
req_id = str(uuid.uuid4()) # 制造一个固定的 request_id
payload = {
    "filename": "idempotency.txt", 
    "content": "This should only appear ONCE.\n",
    "request_id": req_id  # 伪造网关发出的唯一小票
}

print("🚀 Sending FIRST request (Original)...")
resp1 = requests.post(f"{GATEWAY_URL}/create", json=payload)
print(f"Response 1: {resp1.json()}")

print("\n🚀 Sending SECOND request (Simulated Gateway Retry)...")
resp2 = requests.post(f"{GATEWAY_URL}/create", json=payload)
print(f"Response 2: {resp2.json()}")