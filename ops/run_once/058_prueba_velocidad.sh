#!/bin/bash
# 1) Verifica el decodificador rápido con creaciones reales de hoy. 2) Si funciona, arranca la prueba de velocidad con micro-compras.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, sys, requests
from fomo_intel.live.helius_watch import decode_create_from_logs
rpc = f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
cases = {"24YTARWpvxS21kg7Ha4Jp2pq8seP8kK57GyZb2WGeEgiFgJUTuusKWvKfkcaHeYGQVgRDJBVWPrz7Ja7jAZPkFSE": ("B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC", "4NWSwmboxz"),
         "5M2rpQ5H3AmRtT4NRS9ueAkzzwaEW4D2AzGBbcUucyRpRzCKWNX1pKQWwpM4Y8xfQG9azi6orHtVbCpJCuYVpCoV": ("gVDXhoGbePACvSqN7CZBtQXFW9eyJwsgudPEwSydAkx", "rjALAN7kNC")}
ok = True
for tx, (dev, want) in cases.items():
    r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [tx, {"encoding": "json", "maxSupportedTransactionVersion": 1}]}, timeout=30).json()["result"]
    out = decode_create_from_logs(r["meta"]["logMessages"], dev)
    print(want, "->", out)
    if not out or not out["mint"].startswith(want) or out["initial_sol"] <= 0: ok = False
open("state/ops/decoder_ok", "w").write("1" if ok else "0")
print("DECODIFICADOR", "OK" if ok else "FALLA")
PY
if [ "$(cat state/ops/decoder_ok)" = "1" ]; then
python3 - <<'PY'
import json, os, time
p = "state/control.json"; d = json.load(open(p))
d.update({"size_usd": 1.0, "max_open": 3, "priority_fee_sol": 0.002, "swap_slippage_pct": 25.0, "max_slippage_pct": 40.0,
          "factory_tp": 3.0, "factory_max_hold_s": 180, "factory_stop": 0.7, "daily_loss_usd": 30.0})
json.dump(d, open(p, "w"), indent=1)
json.dump({"start": time.time(), "start_sol": None, "mode": "real", "strategy": "factory", "nota": "prueba de velocidad: micro-compras 0,01 SOL"}, open("state/session_speed.json", "w"))
if os.path.exists("state/STOP"): os.remove("state/STOP")
print("prueba de velocidad ACTIVA:", {k: d[k] for k in ("size_usd", "priority_fee_sol", "swap_slippage_pct", "factory_tp", "factory_max_hold_s")})
PY
fi
systemctl restart fomo-live; sleep 5; systemctl is-active fomo-live; journalctl -u fomo-live --no-pager -n 3
