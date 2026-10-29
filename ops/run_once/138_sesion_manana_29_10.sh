#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== anti-rug de posiciones abiertas ==="
timeout 1200 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz DEW9dSN6QpWyNthphCpMmAbZP1Q4cEKR9xQXAri98WDP 33jENUQnjoitkMFpvNJcSHyLAHFWJuHwT6E3E8CNpump 6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr | grep -v "^detalle"
echo; echo "=== posiciones: datos actuales ==="
for M in 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz DEW9dSN6QpWyNthphCpMmAbZP1Q4cEKR9xQXAri98WDP 33jENUQnjoitkMFpvNJcSHyLAHFWJuHwT6E3E8CNpump 6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr; do
  curl -s -H "x-api-key: $SOLANATRACKER_API_KEY" "https://data.solanatracker.io/tokens/$M" | python3 -c "
import json,sys
d=json.load(sys.stdin); t=d.get('token',{}); p=(d.get('pools') or [{}])[0]; e=d.get('events',{})
print(t.get('symbol'),'mcap',round(p.get('marketCap',{}).get('usd',0)),'liq',round(p.get('liquidity',{}).get('usd',0)),'vol24',round((p.get('txns') or {}).get('volume24h',0) or 0),'holders',d.get('holders'))
print('  cambios',{k:round(v.get('priceChangePercentage',0),1) for k,v in e.items()})
print('  riesgo',json.dumps(d.get('risk',{}).get('bundlers',{}))[:200], 'top10',d.get('risk',{}).get('top10'))
" 2>&1 | head -5
done
echo; echo "=== scan4 + anti-rug top 5 ==="
timeout 600 python3 -u -m fomo_intel.desk.scan4
TOP=$(cat state/desk/scan4_top.txt 2>/dev/null)
echo "top: $TOP"
[ -n "$TOP" ] && timeout 900 python3 -u -m fomo_intel.desk.dd $TOP | grep -v "^detalle"
