import os
import time
import uuid

print("--- 1. Initializing Resilience Test File ---")
os.system("""docker exec finance-gateway python -c "import requests, uuid; from requests_gssapi import HTTPSPNEGOAuth; requests.post('http://localhost:9000/finance/create', json={'filename': 'report_robust.txt', 'content': 'Base\\n', 'request_id': str(uuid.uuid4())}, auth=HTTPSPNEGOAuth())" """)

print("\n🚀 2. Simulating Disaster: Powering Off client-finance1 (Docker Stop)...")
os.system("docker stop client-finance1")
time.sleep(2)

print("\n🚀 3. Sending 3 Write Requests to Gateway while finance1 is DOWN...")
for i in range(1, 4):
    req_id = str(uuid.uuid4())
    print(f"   -> Sending Disaster-Period Data {i}...")
    cmd = f"""docker exec finance-gateway python -c "import requests; from requests_gssapi import HTTPSPNEGOAuth; requests.post('http://localhost:9000/finance/write', json={{'filename': 'report_robust.txt', 'content': 'Written while finance1 is DEAD ({i})\\n', 'request_id': '{req_id}'}}, auth=HTTPSPNEGOAuth())" """
    os.system(cmd)
    time.sleep(0.5)

print("\n🚀 4. Disaster Recovery: Rebooting client-finance1...")
os.system("docker start client-finance1")
print("   -> Waiting for RabbitMQ Reconnection and Persistent Queue Consumption (10s)...")
time.sleep(10)

print("\n🔍 5. Reading File Directly from finance1's Physical Disk!")
print("   (If robust is successful, it will automatically pull the 3 missed data entries from MQ upon reboot)")
print("-" * 40)
os.system("docker exec client-finance1 cat /data/report_robust.txt")
print("-" * 40)

# python3 eval_robust.py