#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os
from fomo_intel.live.wallet import Rpc
from fomo_intel.live.config import Env
rpc = Rpc(Env().rpc_url)
L = "G9DYnzG3tHPvuanEc4nB5qCj7TWYUPvv9gkib9sEahek"; E = "8UhBd1jB3MxVZam13UQnbV1EYL7eXhZbWBY5bA5x7Y82"; T = "EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4"
for name, w in (("lloyd", L), ("equilibrado", E), ("tradicional", T)):
    print(name, "SOL", round(rpc.sol_balance(w), 5))
    for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
        r = rpc.call("getTokenAccountsByOwner", [w, {"programId": prog}, {"encoding": "jsonParsed"}]) or {}
        for a in r.get("value", []):
            i = a["account"]["data"]["parsed"]["info"]
            if float(i["tokenAmount"]["uiAmount"] or 0) > 0: print("   ", i["mint"][:10], i["tokenAmount"]["uiAmount"])
for sig in ("avyKvNEbFhuHv448", "2rXNWhYvBwHPa74R", "ZCuYPuzsPFNxKQg6"):
    pass
mig = json.load(open("state/plan_lloyd/migration.json"))
for src, rows in mig["moved"].items():
    for r in rows:
        sig = r[2]; st = (rpc.call("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}]) or {}).get("value", [None])[0]
        print(src, r[0][:10], r[1], sig[:14], "→", (st or {}).get("confirmationStatus"), (st or {}).get("err"))
pos = json.load(open("state/plan_lloyd/positions.json")); print("positions.json:", {k[:8]: (v["symbol"], v.get("sleeve"), round(v["tokens"], 3)) for k, v in pos.items()})
s = json.load(open("state/plan_lloyd_summary.json")); print("summary:", [(p["symbol"], p["tokens"]) for p in s["positions"]])
PY
journalctl -u fomo-desk@lloyd --no-pager -n 25 | grep -iv "decisión auto-lloyd-20261029-0156" | tail -15
