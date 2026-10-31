#!/bin/bash
# 31/10 11:25 — Gastón depositó en la billetera de la lotería: verificar saldo, modo live y primeras compras.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
echo live > state/desk/floor_mode
echo "fomo-floor: $(systemctl is-active fomo-floor)"
python3 - <<'PY'
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env
from fomo_intel.live.wallet import Rpc
r=Rpc(Env().rpc_url); print("saldo SOL:", r.sol_balance("HrRBytKRDJyhuYT9C5WAKs5jQ7ZRJPyZoQ3FRth2RXHK"))
PY
sleep 240
python3 -c "import json;d=json.load(open('state/desk/floor.json'));print({k:d[k] for k in ('mode','sol_balance','open','closed','bought_today','stats')})"
echo "--- eventos:"; tail -8 state/desk/floor_log.jsonl 2>/dev/null
journalctl -u fomo-floor --no-pager -n 8 | cut -c1-250
