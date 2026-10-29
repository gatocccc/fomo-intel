#!/bin/bash
# Prueba REAL mínima del ejecutor de perps: short SOL con 10 USDC a 2x desde la billetera del libro, y cierre 90 s después.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, logging, time
from pathlib import Path
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env
from fomo_intel.live.wallet import Rpc, load_or_create
from fomo_intel.live.perps import JupPerps
kp = load_or_create(Path("secrets/plan_lloyd.json")); rpc = Rpc(Env().rpc_url)
P = JupPerps(kp, rpc)
print("USDC antes:", P.usdc_balance(), "SOL:", round(rpc.sol_balance(str(kp.pubkey())), 4))
r = P.open("SOL", "short", 10, 2, dry=False)
print("OPEN:", json.dumps({k: r.get(k) for k in ("ok", "sig", "position_pubkey", "error", "path_used")}))
print("attempts:", json.dumps(r.get("attempts"))[:600])
pos = []
for i in range(12):
    time.sleep(10); pos = P.positions()
    if pos: break
print("positions tras abrir:", json.dumps(pos)[:800])
print("USDC después de abrir:", P.usdc_balance())
if pos:
    time.sleep(30)
    c = P.close(pos[0]["pubkey"], dry=False)
    print("CLOSE:", json.dumps({k: c.get(k) for k in ("ok", "sig", "error", "path_used")}))
    print("attempts:", json.dumps(c.get("attempts"))[:600])
    for i in range(12):
        time.sleep(10)
        if not P.positions(): break
    print("positions tras cerrar:", P.positions())
print("USDC final:", P.usdc_balance(), "SOL:", round(rpc.sol_balance(str(kp.pubkey())), 4))
json.dump({"ts": time.time(), "open": r, "positions": pos}, open("state/ops/perps_test.json", "w"), default=str)
PY
