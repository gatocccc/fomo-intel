#!/bin/bash
# a) ¿cómo se identifica al creador real de un token de Bags? (deployer en search = wallet de la plataforma)
# b) análisis del universo pump.fun si la descarga terminó
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u - <<'PY' 9>&-
import json, os, requests
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
d = requests.get(f"{B}/search", headers=h, params={"launchpad": "bags", "limit": 2, "sortBy": "createdAt", "sortOrder": "desc"}, timeout=30).json()
t = d["data"][0]; print("search bags: deployer", t.get("deployer"), "| tokenDetails", t.get("tokenDetails"), "| socials", t.get("socials"))
mint = t["mint"]
info = requests.get(f"{B}/tokens/{mint}", headers=h, timeout=30).json()
tk = info.get("token", {}); print("token.creation:", tk.get("creation"), "| creator:", tk.get("creator"), "| creators:", tk.get("creators"), "| createdOn:", tk.get("createdOn"), tk.get("createdOnName"), "| twitter:", tk.get("twitter"))
print("risk.dev:", (info.get("risk") or {}).get("dev"))
fb = requests.get(f"{B}/v2/pnl/tokens/{mint}/first-buyers", headers=h, params={"limit": 5}, timeout=30).json()
for x in (fb.get("traders") or [])[:5]: print("  first buyer:", x.get("wallet"), x.get("identity"), (x.get("timing") or {}).get("firstTrade"))
# bags API pública sin clave: creador
for u in (f"https://api2.bags.fm/api/v1/token-launch/creator/v3?tokenMint={mint}", f"https://public-api-v2.bags.fm/api/v1/token-launch/creator/v3?tokenMint={mint}", f"https://api2.bags.fm/api/v1/token-launch?tokenMint={mint}"):
    try:
        r = requests.get(u, timeout=20); print("bags", u.split('/api/v1/')[1][:40], "->", r.status_code, r.text[:400].replace("\n", " "))
    except Exception as e: print("bags err", e)
PY
if ! pgrep -f "experiments.red pull pump" >/dev/null; then timeout 280 python3 -u -m fomo_intel.experiments.red analyze pump 9>&-; else echo "pump todavía descargando"; tail -3 state/ops/exp_pump.log; fi
