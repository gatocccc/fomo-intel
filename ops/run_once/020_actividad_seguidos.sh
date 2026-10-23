#!/bin/bash
# ¿Operaron las 8 billeteras seguidas en las últimas horas? (contraste con lo que llegó por PumpPortal)
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
ws = json.load(open("state/follow_list.json"))["wallets"]; now = time.time()
for w in ws:
    try:
        tr = requests.get(f"{B}/wallet/{w}/trades", headers=h, params={"limit": 30}, timeout=30).json().get("trades", [])
    except Exception as e: print(w[:8], "error", e); continue
    rec = [t for t in tr if now - t.get("time", 0)/1000 < 3*3600]
    last = max((t.get("time", 0) for t in tr), default=0)
    pools = {t.get("program") for t in rec}
    print(f"{w[:8]}… últimas 3 h: {len(rec)} trades ; último trade hace {((now - last/1000)/3600):.1f} h ; programas: {pools}")
    for t in rec[:3]:
        print("     ", json.dumps({k: t.get(k) for k in ("time", "program", "type")}), (t.get("to") or {}).get("address", "")[:10], (t.get("from") or {}).get("address", "")[:10])
PY
