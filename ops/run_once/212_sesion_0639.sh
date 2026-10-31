#!/bin/bash
# 31/10 06:39 ART — sesión: GTA6 tras el stop (¿se derrumbó o fue mecha?), mercado, escaneo (veto).
cd /root/fomo_intel || exit 1; set -a; . ./.env; set +a
echo "=== GTA6 dexscreener ==="
curl -s -m 20 "https://api.dexscreener.com/latest/dex/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz" | python3 -c "
import sys,json
d=json.load(sys.stdin)['pairs'];p=max(d,key=lambda x:(x.get('liquidity') or {}).get('usd',0))
print(p['baseToken']['symbol'],p['priceUsd'],'mcap',p.get('marketCap'),'liq',p['liquidity']['usd'],'chg',p['priceChange'],'vol',p['volume'],'txns',p.get('txns',{}).get('h24'))"
echo "=== GTA6 velas 1h (geckoterminal, últimas 30) ==="
curl -s -m 20 "https://api.geckoterminal.com/api/v2/networks/solana/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz/pools" | python3 -c "
import sys,json;d=json.load(sys.stdin)['data'];print(d[0]['id'])" > /tmp/gp 2>/dev/null
P=$(cat /tmp/gp | sed 's/solana_//'); echo pool $P
curl -s -m 20 "https://api.geckoterminal.com/api/v2/networks/solana/pools/$P/ohlcv/hour?limit=30" | python3 -c "
import sys,json,time;l=json.load(sys.stdin)['data']['attributes']['ohlcv_list']
for t,o,h,lo,c,v in reversed(l): print(time.strftime('%d %H:%M',time.gmtime(t)),round(o,5),round(h,5),round(lo,5),round(c,5),int(v))"
echo "=== majors ==="
curl -s -m 20 "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22SOLUSDT%22,%22BTCUSDT%22,%22ETHUSDT%22%5D" | python3 -c "
import sys,json;[print(x['symbol'],x['lastPrice'],x['priceChangePercent']) for x in json.load(sys.stdin)]"
echo "=== scan4 (veto) ==="
timeout 300 python3 -u -m fomo_intel.desk.scan4 2>&1 | grep -v "^  err" | tail -25
echo "=== lab ==="
python3 -c "
import json;s=json.load(open('state/plan_lab_summary.json'));print('lab eq',s.get('equity_usd'),[(p.get('symbol'),p.get('value_usd')) for p in s.get('positions',[])])"
