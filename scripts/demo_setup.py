"""生成两条演示会话，方便打开管理台就能看到数据。"""
import json

import httpx

BASE = "http://127.0.0.1:8000"


def login(username, password):
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": username, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def ask(token, question, thread):
    answer = ""
    with httpx.stream(
        "POST",
        f"{BASE}/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": question, "thread_id": thread},
        timeout=120,
    ) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                if raw.startswith("data:"):
                    payload = raw[5:].strip()
                    if payload != "[DONE]":
                        evt = json.loads(payload)
                        if evt["type"] == "token":
                            answer += evt["text"]
    print(f"[demo] {thread}: {answer[:60].replace(chr(10), ' ')}…")


token = login("user01", "user123")
ask(token, "内衣拆封了还能退吗？", "demo_policy")
ask(token, "我要退货，订单号 SN20241115003，手表不想要了", "demo_refund")
print("[demo] 完成：2 条会话 + 1 条高额退款待审工单")
