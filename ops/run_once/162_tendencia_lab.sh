#!/bin/bash
# 30/10 (sesión en vivo): prueba de tendencia diaria en majors desde el lab (fomo_intel/desk/trend.py, enganchada al radar).
# El cambio en fomo_intel/desk/ reinicia radar/motores solo; acá se verifica que arrancó, la señal y la posición.
cd /root/fomo_intel
set -a; . ./.env; set +a
sleep 120
echo "--- trend.json"; python3 -c "import json;d=json.load(open('state/desk/trend.json'));print({k:(v['signal'],v['vol']) for k,v in d['signals'].items()}, d['px'], d['mode']);print(json.dumps(d.get('position'))[:600])"
echo "--- radar log trend"; grep '"trend_' state/desk/radar_log.jsonl | tail -3 | cut -c1-400
echo "--- radar journal"; journalctl -u fomo-radar --no-pager --since "-4 min" | grep -i "trend\|error\|Traceback" | tail -8 | cut -c1-300
echo "--- posiciones perps del lab"; PYTHONPATH=. timeout 60 python3 scripts/perps_probe.py positions --wallet secrets/plan_lab.json 2>&1 | head -30 | cut -c1-300
echo "--- lab summary"; python3 -c "import json;d=json.load(open('state/plan_lab_summary.json'));print(d['equity_usd'], d.get('perps_pnl_usd'))"
