#!/bin/bash
# Genera las tres billeteras de los planes del piloto automático (agresivo, equilibrado, tradicional).
# Las claves quedan solo en secrets/ (600); se publican únicamente las direcciones en state/plan_wallets.json.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json
from pathlib import Path
from fomo_intel.live.wallet import load_or_create
out = {}
for plan in ("agresivo", "equilibrado", "tradicional"):
    kp = load_or_create(Path(f"secrets/plan_{plan}.json"))
    out[plan] = str(kp.pubkey())
    print(plan, out[plan])
json.dump(out, open("state/plan_wallets.json", "w"), indent=1)
PY
ls -l secrets/
echo "--- dependencias para la app"
python3 -m pip install -q --break-system-packages "eth-account>=0.11" 2>&1 | tail -2
python3 -c "import eth_account; print('eth_account', eth_account.__version__)"
echo "--- certbot"; which certbot; certbot --version 2>&1
echo "--- htpasswd"; ls -l /etc/nginx/.htpasswd_fomo
echo "--- puertos en uso"; ss -ltnp | grep -E '87[0-9][0-9]' || true
