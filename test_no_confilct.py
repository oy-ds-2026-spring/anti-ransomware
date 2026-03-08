import requests
import threading
import time

GATEWAY_URL = "http://localhost:9000/finance"

def make_independent_write(thread_id):
    """每个线程只操作属于自己的独立文件，互不干扰"""
    filename = f"independent_file_{thread_id}.txt"
    try:
        # 1. 并发创建各自的文件
        requests.post(f"{GATEWAY_URL}/create", json={"filename": filename, "content": f"Init {thread_id}\n"}, timeout=5)
        
        time.sleep(1)
        
        # 2. 并发写入各自的文件
        payload = {"filename": filename, "content": f"Data from Thread {thread_id} is safe!\n"}
        resp = requests.post(f"{GATEWAY_URL}/write", json=payload, timeout=10)
        
        print(f"✅ Thread {thread_id} successfully wrote to {filename} (HTTP {resp.status_code})")
    except Exception as e:
        print(f"❌ Thread {thread_id} failed: {e}")

print("🚀 [Step 1] Starting 10 concurrent threads...")
print("⚠️ These threads will hit the Gateway AT THE SAME TIME, but write to DIFFERENT files.")

threads = []
for i in range(1, 5):
    t = threading.Thread(target=make_independent_write, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print("\n🎉 All independent writes completed!")
print("👀 Open your browser and check the directory:")
print("👉 http://localhost:9000/browse/")