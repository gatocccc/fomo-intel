#!/bin/bash
# 31/10 21:39 ART — sesión: stools vs libro, GTA6 precio + anti-rug, escaneo (veto).
cd /root/fomo_intel || exit 1; set -a; . ./.env; set +a
python3 - <<'PY'
import json, glob, os
s = json.load(open("state/plan_lloyd_summary.json")); print("libro eq", s.get("equity_usd"), [(p.get("symbol"), p.get("value_usd")) for p in s.get("positions", [])])
for f in sorted(glob.glob("state/users/*_summary.json")):
    s = json.load(open(f)); uid = s.get("user_id")
    if not s.get("started"): continue
    perps = json.load(open(f"state/users/{uid}/perps.json")) if os.path.exists(f"state/users/{uid}/perps.json") else {}
    print(f"[{uid}] eq={s.get('equity_usd')} cash={s.get('cash_usd')} perps_open={s.get('perps_open')}")
    for k, p in perps.items():
        print(f"     {k}: coll={p.get('collateral_usd')} size={p.get('size_usd')} entry={p.get('entry')} pnl={p.get('pnl_usd')} closed={p.get('closed')} err={p.get('error')}")
PY
echo "== mirror log =="; journalctl -u fomo-mirror --no-pager -n 25 2>&1 | grep -v systemd | tail -25
echo "=== GTA6 dexscreener ==="
curl -s -m 20 "https://api.dexscreener.com/latest/dex/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz" | python3 -c "
import sys,json
d=json.load(sys.stdin)['pairs'];p=max(d,key=lambda x:(x.get('liquidity') or {}).get('usd',0))
print(p['baseToken']['symbol'],p['priceUsd'],'mcap',p.get('marketCap'),'liq',p['liquidity']['usd'],'chg',p['priceChange'],'vol',p['volume'])"
echo "=== anti-rug GTA6 ==="
timeout 200 python3 -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 2>&1 | tail -15
echo "=== scan4 (veto) ==="
timeout 300 python3 -u -m fomo_intel.desk.scan4 2>&1 | grep -v "^  err" | tail -25
