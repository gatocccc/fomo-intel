#!/bin/bash
# Descubrimiento: qué devuelven los endpoints de ranking de traders y PnL por billetera de Solana Tracker.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}
B = "https://data.solanatracker.io"
def get(path, **p):
    r = requests.get(B + path, headers=h, params=p, timeout=30)
    try: j = r.json()
    except Exception: j = r.text
    s = json.dumps(j)[:900] if not isinstance(j, str) else j[:300]
    print(f"\n### GET {path} {p} -> {r.status_code}\n{s}")
    return j if r.ok else None
tt = get("/top-traders/all", page=1, sortBy="total", expandPnl="true")
tt2 = get("/top-traders/all/1", sortBy="winPercentage", expandPnl="true")
lb = get("/v2/pnl/leaderboard/top", days=30, sort="realized", direction="desc", limit=50)
lb2 = get("/v2/pnl/leaderboard/top", days=7, sort="winPercentage", limit=50)
# una billetera del ranking para ver el PnL detallado
w = None
for src in (tt, tt2, lb, lb2):
    if isinstance(src, dict):
        rows = src.get("wallets") or src.get("traders") or src.get("data") or []
    elif isinstance(src, list): rows = src
    else: rows = []
    if rows:
        w = rows[0].get("wallet") or rows[0].get("address") if isinstance(rows[0], dict) else None
        if w: break
print("\nbilletera de muestra:", w)
if w:
    get(f"/pnl/{w}", showHistoricPnL="true", hideDetails="true")
    get(f"/pnl/{w}", hideDetails="true")
    d = get(f"/wallet/{w}/trades", limit=20)
    get(f"/wallet/{w}/basic")
PY
