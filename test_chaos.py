import requests
import threading
import time

GATEWAY_URL = "http://localhost:9000/finance"
TEST_FILE = "concurrent_target.txt"

# 1. 先初始化一个靶子文件
requests.post(f"{GATEWAY_URL}/create", json={"filename": TEST_FILE, "content": "START\n"})
time.sleep(1) # 等待全网同步完成

def make_write_request(thread_id):
    """模拟并发用户疯狂写入"""
    try:
        payload = {"filename": TEST_FILE, "content": f"Data from Thread {thread_id}\n"}
        # 网关会把这 10 个请求瞬间散布到 4 个 Finance 节点上
        resp = requests.post(f"{GATEWAY_URL}/write", json=payload)
        print(f"Thread {thread_id} got HTTP {resp.status_code}")
    except Exception as e:
        print(f"Thread {thread_id} failed: {e}")

# 2. 释放 10 个并发线程瞬间撞击网关
threads = []
for i in range(1, 11):
    t = threading.Thread(target=make_write_request, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print("\nAll writes dispatched! Check the file via Gateway: http://localhost:9000/browse/concurrent_target.txt")