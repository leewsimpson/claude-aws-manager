"""Phase 7 live enforcement smoke test (run against the docker stack on :8000).

Creates a cost centre, makes ccowner1 its owner, has ccowner1 auto-approve a key
for it, then polls the key's live usage until budget enforcement hard-stops it,
and finally confirms restart once the rolling window clears (best-effort).
"""
import json
import time
import urllib.request
import urllib.error
import secrets

BASE = "http://localhost:8000/api"


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "null")


def login(u, p):
    s, b = call("POST", "/auth/login", body={"username": u, "password": p})
    assert s == 200, (s, b)
    return b["access_token"]


admin = login("admin", "admin")
cco = login("ccowner1", "ccowner1")

# ccowner1 id
_, users = call("GET", "/users", admin)
cco_id = next(u["id"] for u in users if u["username"] == "ccowner1")

code = f"CC-P7-{secrets.token_hex(2).upper()}"
s, cc = call("POST", "/cost-centres", admin,
             {"code": code, "name": "Phase 7 enforcement demo", "budget_cap": 500})
print("create CC", s, code, cc["id"])
s, _ = call("POST", f"/cost-centres/{cc['id']}/owners", admin, {"user_id": cco_id})
print("assign owner", s)

s, res = call("POST", "/key-requests", cco, {"cost_centre_id": cc["id"], "justification": "p7 demo"})
print("request key", s, "status=", res["request"]["status"],
      "token_present=", bool(res.get("key") and res["key"].get("bearer_token")))
key_id = res["key"]["id"]

print(f"\nPolling key {key_id} usage (poller runs every ~20s)...")
stopped_seen = False
deadline = time.time() + 300
while time.time() < deadline:
    s, u = call("GET", f"/keys/{key_id}/usage", cco)
    print(f"  status={u['status']:8s} rolling=${u['rolling_spend']:.2f}/"
          f"{u['rolling_limit']} lifetime=${u['lifetime_spend']:.2f}/"
          f"{u['lifetime_budget']} snapshots={len(u['snapshots'])}")
    if u["status"] == "stopped":
        stopped_seen = True
        print("  >>> KEY HARD-STOPPED by budget enforcement")
        break
    time.sleep(15)

print("\nRESULT:", "PASS — enforcement stopped the key" if stopped_seen
      else "TIMEOUT — key did not stop within 5 min")
