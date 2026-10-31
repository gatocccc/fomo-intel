#!/bin/bash
# 31/10 11:50 — verificar que /api/lab publica la lotería en el piso y que la página la muestra.
cd /root/fomo_intel || exit 1
sleep 90
echo "fomo-app $(systemctl is-active fomo-app) · fomo-floor $(systemctl is-active fomo-floor)"
python3 -c "import json;d=json.load(open('state/desk/floor.json'));print({k:d.get(k) for k in ('start_sol','equity_sol','open','closed','stats')})"
PORT=$(grep -o 'port[^0-9]*[0-9]\{4\}' fomo_intel/app/server.py | head -1 | grep -o '[0-9]\{4\}')
for u in "http://127.0.0.1:${PORT:-8090}/api/lab" "https://app.nonconformistducks.com/api/lab"; do
  curl -s -m 15 "$u" | python3 -c "import sys,json;d=json.load(sys.stdin);f=d.get('floor');print('$u', json.dumps(f)[:700] if f else 'SIN floor')" 2>&1 | head -3
done
grep -c "floor-sect" /var/www/autopilot/lab/index.html
