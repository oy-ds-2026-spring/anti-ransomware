import os
import time
import uuid

# 生成一个全局唯一的测试 ID
req_id = str(uuid.uuid4())

print("🚨 1. Triggering Lockdown on finance1 via Detection Service gRPC...")
# 使用 os.system 在 detection 容器内执行锁定命令
os.system('docker exec detection-service python -c "from detection.detection import trigger_client_lockdown; trigger_client_lockdown(\'finance1\', \'TEST-999\', \'Manual Health Test\')"')
time.sleep(2)

print(f"\n🚀 2. Sending Write Request to a HEALTHY node (finance2) (Request ID: {req_id[:8]}...)")
# 借助网关的 Kerberos 票据，直接将带有 request_id 的数据写给健康的 finance2
cmd2 = f"""docker exec finance-gateway python -c "import requests; from requests_gssapi import HTTPSPNEGOAuth; print(requests.post('http://client-finance2:5000/create', json={{'filename': 'health_test.txt', 'content': 'Data written while dead\\n', 'request_id': '{req_id}'}}, auth=HTTPSPNEGOAuth()).json())" """
os.system(cmd2)

print("\n⏳ Waiting for MQ broadcast... Check 'docker logs client-finance1'")
print("   (You should see: [HEALTH] Node locked down. Discarding sync msg...)")
time.sleep(3)

print("\n🔓 3. Unlocking finance1...")
# 借助网关权限调用解锁接口
cmd3 = """docker exec finance-gateway python -c "import requests; from requests_gssapi import HTTPSPNEGOAuth; requests.post('http://client-finance1:5000/unlock', auth=HTTPSPNEGOAuth())" """
os.system(cmd3)
time.sleep(1)

print("\n🔁 4. Simulating Recovery Service 'Log Replay' with the SAME request_id...")
# 恢复健康后，模拟 Recovery 引擎重放这条日志（发给 finance1）
cmd4 = f"""docker exec finance-gateway python -c "import requests; from requests_gssapi import HTTPSPNEGOAuth; print(requests.post('http://client-finance1:5000/create', json={{'filename': 'health_test.txt', 'content': 'Data written while dead\\n', 'request_id': '{req_id}'}}, auth=HTTPSPNEGOAuth()).json())" """
os.system(cmd4)

print("\n🛡️ 5. Simulating DUPLICATE 'Log Replay' (Idempotency Check)...")
# 再次重放，验证幂等性拦截
os.system(cmd4)