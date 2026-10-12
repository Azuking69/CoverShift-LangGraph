import os
import time

import requests

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001")
store, period = f"c-check-{int(time.time())}", "2026-10"
tid = f"{store}-{period}"
print("1. start:", requests.post(f"{API_BASE}/api/v1/shift/start", json={"store_id": store, "period": period}).json())
for _ in range(40):
    s = requests.get(f"{API_BASE}/api/v1/shift/{tid}").json().get("status")
    print("  status:", s)
    if s == "PAUSED_FOR_APPROVAL":
        break
    time.sleep(0.5)
print("2. resume:", requests.post(f"{API_BASE}/api/v1/shift/resume", json={"thread_id": tid, "approved": True}).json())
for _ in range(40):
    s = requests.get(f"{API_BASE}/api/v1/shift/{tid}").json().get("status")
    print("  status:", s)
    if s == "COMPLETED":
        break
    time.sleep(0.5)
