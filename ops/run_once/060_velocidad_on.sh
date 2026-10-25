#!/bin/bash
# Prueba de velocidad con micro-compras (0,01 SOL): B32Q (la que pidió Gastón) y gVDX. Salida: cuando la fábrica vende, +50% o a los 20 s.
cd /root/fomo_intel
python3 - <<'PY'
import json, os, time
json.dump({"wallets": ["B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC", "gVDXhoGbePACvSqN7CZBtQXFW9eyJwsgudPEwSydAkx"], "updated": time.time(),
           "nota": "prueba de velocidad 25/10 20:10"}, open("state/factories.json", "w"), indent=1)
p = "state/control.json"; d = json.load(open(p))
d.update({"size_usd": 1.0, "max_open": 3, "priority_fee_sol": 0.002, "swap_slippage_pct": 25.0, "max_slippage_pct": 40.0,
          "factory_tp": 1.5, "factory_max_hold_s": 20, "factory_stop": 0.5, "daily_loss_usd": 30.0})
json.dump(d, open(p, "w"), indent=1)
json.dump({"start": time.time(), "start_sol": None, "mode": "real", "strategy": "factory", "nota": "prueba de velocidad"}, open("state/session.json", "w"), indent=1)
if os.path.exists("state/STOP"): os.remove("state/STOP")
print({k: d[k] for k in ("mode", "size_usd", "priority_fee_sol", "factory_tp", "factory_max_hold_s", "factory_stop")})
PY
python3 - <<'PY'
import json, time
from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
import os
for l in open(".env"):
    if "=" in l: k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
s = Rpc(Env().rpc_url).sol_balance(json.load(open("state/wallet_pub.json"))["pubkey"])
d = json.load(open("state/session.json")); d["start_sol"] = round(s, 4); json.dump(d, open("state/session.json", "w"), indent=1); print("saldo inicial prueba:", s)
PY
systemctl restart fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 3
