#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== precios (dexscreener) ==="
for m in 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz So11111111111111111111111111111111111111112; do
curl -s -m 20 "https://api.dexscreener.com/latest/dex/tokens/$m" | python3 -c "
import sys,json
d=json.load(sys.stdin)['pairs'];p=max(d,key=lambda x:(x.get('liquidity') or {}).get('usd',0))
print(p['baseToken']['symbol'],p['priceUsd'],'mcap',p.get('marketCap'),'liq',p['liquidity']['usd'],'chg',p['priceChange'],'vol',p['volume'])"
done
curl -s -m 20 "https://api.coingecko.com/api/v3/simple/price?ids=solana,bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"; echo
echo "=== scan4 (veto, top) ==="
timeout 400 python3 -u -m fomo_intel.desk.scan4 2>&1 | grep -v "^  err" | tail -40
