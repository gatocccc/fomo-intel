#!/bin/bash
# 30/10: verificación tras agregar reintentos + RPC de respaldo (429 de Helius frenaba la apertura de perps de trend/tortuga).
cd /root/fomo_intel
sleep 240
grep -E '"(turtle|trend)_' state/desk/radar_log.jsonl | tail -4 | cut -c1-500
python3 -c "import json;d=json.load(open('state/desk/trend.json'));print('trend pos', json.dumps(d.get('position'))[:500])"
python3 -c "import json;d=json.load(open('state/desk/levels.json'));[print(c,v['px'],v['short_below'],v['to_short'],json.dumps(v['position'])[:300]) for c,v in d['view'].items()]"
PYTHONPATH=. timeout 60 python3 scripts/perps_probe.py positions --wallet secrets/plan_lab.json 2>&1 | tail -3 | cut -c1-600
PYTHONPATH=. timeout 60 python3 scripts/perps_probe.py positions --wallet secrets/plan_lloyd.json 2>&1 | tail -3 | cut -c1-600
curl -s localhost:8090/api/book 2>/dev/null | python3 -c "import json,sys;d=json.load(sys.stdin);print('armed',d.get('armed'));print('perps',d.get('perps'))" 2>&1 | head -5
grep -n "8090\|port" fomo_intel/app/server.py | head -3
