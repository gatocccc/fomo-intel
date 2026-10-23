#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os
from fomo_intel.live.wallet import Rpc
from fomo_intel.live.config import Env
pub = json.load(open("state/wallet_pub.json"))["pubkey"]
print("saldo", pub, Rpc(Env().rpc_url).sol_balance(pub), "SOL")
PY
