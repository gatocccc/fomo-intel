#!/bin/bash
# 30/10 — verificar que el consenso de KOLs arrancó dentro de fomo-radar
cd /root/fomo_intel || exit 1
sleep 150
systemctl is-active fomo-radar; journalctl -u fomo-radar --since "-6min" --no-pager | grep -i "kols\|helius\|Traceback\|Error" | tail -25
echo "--- state/desk/kols.json"; python3 -c "import json;d=json.load(open('state/desk/kols.json'));print({k:d[k] for k in d if k not in ('buys','hot')});print('hot',d['hot'][:5])" 2>&1
echo "--- lab"; python3 -c "import json;d=json.load(open('state/plan_lab_summary.json'));print('cash_sol',d['cash_sol'],'equity',d['equity_usd'])"
