#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== niveles / tortuga / tendencia lab ==="
for f in state/desk/levels.json state/desk/turtle_pos_book.json state/desk/trend.json state/desk/trend_pos_lab.json; do echo "-- $f"; head -c 1500 $f 2>/dev/null; echo; done
echo "=== perps abiertos (Jupiter) ==="
timeout 120 python3 scripts/perps_probe.py positions 2>&1 | tail -30
echo "=== mesa: journal ultimas lineas ==="
tail -6 state/desk/journal.jsonl | cut -c1-400
echo "=== GTA6 datos ==="
M=4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz
curl -s -H "x-api-key: $SOLANATRACKER_API_KEY" "https://data.solanatracker.io/tokens/$M" | python3 -c "
import json,sys
d=json.load(sys.stdin); t=d.get('token',{}); p=(d.get('pools') or [{}])[0]; e=d.get('events',{})
print(t.get('symbol'),'price',p.get('price',{}).get('usd'),'mcap',round(p.get('marketCap',{}).get('usd',0)),'liq',round(p.get('liquidity',{}).get('usd',0)),'vol24',round((p.get('txns') or {}).get('volume24h',0) or 0),'holders',d.get('holders'))
print('  cambios',{k:round(v.get('priceChangePercentage',0),1) for k,v in e.items()})
" 2>&1 | head -5
echo "=== scan4 + anti-rug (GTA6 + top 5) ==="
timeout 600 python3 -u -m fomo_intel.desk.scan4 | tail -25
TOP=$(cat state/desk/scan4_top.txt 2>/dev/null)
echo "top: $TOP"
timeout 900 python3 -u -m fomo_intel.desk.dd $M $TOP | grep -v "^detalle"
