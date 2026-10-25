#!/bin/bash
# Universo de memecoins con liquidez real (no lanzamientos): qué endpoints de ST sirven y qué tokens hay.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 280 python3 -u - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
def get(p, **q):
    r = requests.get(B + p, headers=h, params=q, timeout=30)
    try: j = r.json()
    except Exception: j = r.text
    return r.status_code, j
seen = {}
for p in ("/tokens/trending/24h", "/tokens/trending", "/tokens/volume/24h", "/tokens/volume", "/top-performers/24h", "/tokens/graduated", "/tokens/multi/graduated"):
    code, j = get(p)
    rows = j if isinstance(j, list) else (j.get("tokens") or j.get("data") or []) if isinstance(j, dict) else []
    print(p, code, "filas:", len(rows))
    for t in rows:
        tk = t.get("token", t); pools = t.get("pools") or []
        mint = tk.get("mint") or t.get("mint")
        if not mint: continue
        liq = max(((pl.get("liquidity") or {}).get("usd") or 0) for pl in pools) if pools else (t.get("liquidityUsd") or 0)
        mc = max(((pl.get("marketCap") or {}).get("usd") or 0) for pl in pools) if pools else (t.get("marketCapUsd") or 0)
        created = min(((pl.get("createdAt") or 9e15) for pl in pools), default=0) if pools else (t.get("createdAt") or 0)
        seen[mint] = {"mint": mint, "sym": tk.get("symbol"), "liq": liq, "mc": mc, "created": created/1000 if created > 1e11 else created, "src": p}
now = time.time()
uni = [t for t in seen.values() if t["liq"] >= 100_000 and 1_000_000 <= t["mc"] <= 500_000_000 and t["created"] and now - t["created"] > 10*86400]
print("\ntokens únicos vistos:", len(seen), "| con liquidez >= US$100K, mcap 1M-500M y > 10 días:", len(uni))
for t in sorted(uni, key=lambda t: -t["liq"])[:60]: print(f"  {t['sym']:<12} liq US${t['liq']:>12,.0f}  mcap US${t['mc']:>14,.0f}  edad {(now-t['created'])/86400:5.0f} d  {t['src']}")
json.dump(uni, open("state/ops/universo_midcaps.json", "w"), indent=1)
PY
