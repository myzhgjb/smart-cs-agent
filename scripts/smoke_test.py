import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


def login(username, password):
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": username, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def ask(token, question, thread):
    headers = {"Authorization": f"Bearer {token}"}
    text, intent, cards, sources = "", "", [], 0
    t0 = time.time()
    with httpx.stream("POST", f"{BASE}/api/v1/chat/stream", headers=headers,
                      json={"question": question, "thread_id": thread}, timeout=120) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                if not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                if payload == "[DONE]":
                    continue
                evt = json.loads(payload)
                if evt["type"] == "intent":
                    intent = evt["label"]
                elif evt["type"] == "sources":
                    sources = len(evt["sources"])
                elif evt["type"] == "card":
                    cards.append(evt["card"]["title"] + "/" + str(evt["card"].get("badge")))
                elif evt["type"] == "token":
                    text += evt["text"]
                elif evt["type"] == "error":
                    text += "[ERR]" + evt["message"]
    print(f"\nQ: {question}")
    print(f"   intent={intent} cards={cards} sources={sources} 用时={time.time()-t0:.1f}s")
    print("   A:", text.replace("\n", " ")[:260])


u = login("user01", "user123")
a = login("admin", "admin123")

ask(u, "内衣拆封了还能退吗？", "test_policy_1")
ask(u, "查一下我的订单 SN20241108001", "test_order_1")
ask(u, "发票开好了吗？", "test_invoice_1")
ask(u, "我要退货，订单号 SN20241116004", "test_refund_block_1")
ask(u, "我要退货，订单号 SN20241108001，耳机降噪有问题", "test_refund_audit_1")
ask(u, "转人工客服", "test_human_1")

print("\n=== 待审工单 ===")
r = httpx.get(f"{BASE}/api/v1/admin/audits?status=pending", headers={"Authorization": f"Bearer {a}"}, timeout=20)
audits = r.json()
for x in audits:
    print("  ", x["code"], x["risk_level"], x["order"]["order_sn"], x["refund"]["amount"], x["refund"]["reason"][:24])

if audits:
    aid = audits[0]["id"]
    r = httpx.post(f"{BASE}/api/v1/admin/audits/{aid}/decide", headers={"Authorization": f"Bearer {a}"},
                   json={"approve": True, "note": "已核实降噪故障，同意退款"}, timeout=20)
    print("  决策:", r.json())

print("\n=== 退款进度复查 ===")
ask(u, "我的退款进度到哪了？", "test_refund_status_1")

print("\n=== 会话列表 ===")
r = httpx.get(f"{BASE}/api/v1/chat/threads", headers={"Authorization": f"Bearer {u}"}, timeout=20)
for t in r.json()[:6]:
    print("  ", t["thread_id"], "|", t["title"], "|", t["count"], "条")
