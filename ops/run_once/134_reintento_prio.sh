#!/bin/bash
# Reintento con comisión de prioridad (las dos que faltan: STONK 253 y USDC 194).
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 900 python3 -u -m fomo_intel.desk.migrate_book --transfer-only
python3 - <<'PY'
from fomo_intel.live.wallet import Rpc
from fomo_intel.live.config import Env
rpc = Rpc(Env().rpc_url)
for name, w in (("lloyd", "G9DYnzG3tHPvuanEc4nB5qCj7TWYUPvv9gkib9sEahek"), ("equilibrado", "8UhBd1jB3MxVZam13UQnbV1EYL7eXhZbWBY5bA5x7Y82"), ("tradicional", "EgkDFMH5oaRrKjo3UWFhGG78hgzxxRMKVbvX9R6MM7o4")):
    print(name, "SOL", round(rpc.sol_balance(w), 5))
    r = rpc.call("getTokenAccountsByOwner", [w, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]) or {}
    for a in r.get("value", []):
        i = a["account"]["data"]["parsed"]["info"]
        if float(i["tokenAmount"]["uiAmount"] or 0) > 0: print("   ", i["mint"][:10], i["tokenAmount"]["uiAmount"])
PY
