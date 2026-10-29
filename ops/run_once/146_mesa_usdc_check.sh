#!/bin/bash
# Verifica que el cerebro de la mesa estacione en USDC el efectivo sin candidato (cambio del 29/10 21:40) y que la orden se ejecute.
cd /root/fomo_intel
sleep 600
journalctl -u fomo-brain --no-pager --since "-12 min" | grep -v httpx | tail -15
echo "--- mesa"; python3 -c "import json;s=json.load(open('state/desk_summary.json'));print('eq',s['equity_usd'],'cash_sol',s['cash_sol'],[(p['symbol'],p.get('value_usd')) for p in s['positions']])"
ls -t desk/decisions 2>/dev/null | head -3; ls -t state/desk/auto 2>/dev/null | head -3
