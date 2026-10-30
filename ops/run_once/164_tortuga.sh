#!/bin/bash
# 30/10 (sesión en vivo): tortuga 55/20 con niveles guardados en el libro (turtle.py) — verificación tras el reinicio.
cd /root/fomo_intel
sleep 300
echo "--- levels.json"; python3 -c "
import json;d=json.load(open('state/desk/levels.json'))
for c,v in d['view'].items(): print(c, 'px',v['px'],'compra≥',round(v['buy_above'],2),'(%+.1f%%)'%(v['to_buy']*100),'corto≤',round(v['short_below'],2),'(%+.1f%%)'%(v['to_short']*100),'salidas',round(v['long_exit_below'],2),round(v['short_exit_above'],2),'pos',json.dumps(v['position'])[:300])"
echo "--- trend.json"; python3 -c "import json;d=json.load(open('state/desk/trend.json'));print({k:v['signal'] for k,v in d['signals'].items()}, json.dumps(d.get('position'))[:400])"
echo "--- log"; grep -E '"(turtle|trend)_' state/desk/radar_log.jsonl | tail -5 | cut -c1-400
journalctl -u fomo-radar --no-pager --since "-6 min" | grep -iE "turtle|trend|Traceback|Error" | tail -8 | cut -c1-300
echo "--- perps lab / libro"; PYTHONPATH=. timeout 60 python3 scripts/perps_probe.py positions --wallet secrets/plan_lab.json 2>&1 | grep -E "symbol|side|size|entry|pubkey" | head -12 | cut -c1-200
PYTHONPATH=. timeout 60 python3 scripts/perps_probe.py positions --wallet secrets/plan_lloyd.json 2>&1 | grep -E "symbol|side|size|entry|pubkey" | head -12 | cut -c1-200
python3 -c "import json;[print(p, json.load(open(f'state/plan_{p}_summary.json'))['equity_usd']) for p in ('lab','lloyd')]"
