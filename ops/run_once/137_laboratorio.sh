#!/bin/bash
# Billetera de laboratorio: ~10% del libro para probar hipótesis en real. La decisión lloyd-2026-10-29-01 vende USDC por SOL; acá se transfiere.
cd /root/fomo_intel; set -a; . ./.env; set +a
sleep 60
timeout 500 python3 -u -m fomo_intel.desk.fund_lab 0.55
systemctl restart fomo-desk@lloyd
python3 - <<'PY'
import json
c = json.load(open("state/brain_config.json")); c.setdefault("modes", {})["lab"] = "off"; json.dump(c, open("state/brain_config.json", "w"))
PY
systemctl enable -q --now fomo-desk@lab; sleep 40
echo "lab: $(systemctl is-active fomo-desk@lab)"; cat state/plan_lab_summary.json | head -c 400; echo
python3 -c "import json;c=json.load(open('state/plan_lloyd/config.json'));print('libro start_usd',c['start_usd'])"
curl -sk --resolve app.nonconformistducks.com:443:127.0.0.1 https://app.nonconformistducks.com/api/lab | head -c 300; echo
