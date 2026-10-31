#!/bin/bash
# 31/10 09:39 ART — sesión de la mañana: majors, escaneo + anti-rug top 5, stools copian perps del libro.
cd /root/fomo_intel || exit 1; set -a; . ./.env; set +a
echo "=== majors ==="
curl -s -m 20 "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22SOLUSDT%22,%22BTCUSDT%22,%22ETHUSDT%22,%22JUPUSDT%22%5D" | python3 -c "
import sys,json;[print(x['symbol'],x['lastPrice'],x['priceChangePercent']) for x in json.load(sys.stdin)]"
echo "=== GTA6 (enfriamiento) ==="
curl -s -m 20 "https://api.dexscreener.com/latest/dex/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz" | python3 -c "
import sys,json
d=json.load(sys.stdin)['pairs'];p=max(d,key=lambda x:(x.get('liquidity') or {}).get('usd',0))
print(p['baseToken']['symbol'],p['priceUsd'],'mcap',p.get('marketCap'),'liq',p['liquidity']['usd'],'chg',p['priceChange'])"
echo "=== stools ==="
python3 - <<'PY'
import json, glob, os
for f in sorted(glob.glob("state/users/*_summary.json")):
    s = json.load(open(f)); uid = s.get("user_id")
    if not s.get("started"): continue
    perps = json.load(open(f"state/users/{uid}/perps.json")) if os.path.exists(f"state/users/{uid}/perps.json") else {}
    print(f"[{uid}] eq={s.get('equity_usd')} cash={s.get('cash_usd')} perps={[(k[:10],p.get('collateral_usd'),p.get('pnl_usd'),p.get('error')) for k,p in perps.items()]}")
PY
echo "=== scan4 + anti-rug top 5 ==="
timeout 330 python3 -u -m fomo_intel.desk.scan4 2>&1 | grep -v "^  err" | tail -22
TOP=$(cat state/desk/scan4_top.txt 2>/dev/null)
[ -n "$TOP" ] && timeout 240 python3 -u -m fomo_intel.desk.dd $TOP 2>&1 | grep -v "^detalle" | tail -30
