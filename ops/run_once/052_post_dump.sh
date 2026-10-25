#!/bin/bash
# ¿Qué pasa con los tokens de las fábricas DESPUÉS de que la fábrica vende en los primeros segundos?
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 280 python3 -u - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
for dev in json.load(open("state/factories.json"))["wallets"] + ["B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC"]:
    d = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    rec = sorted([t for t in d if now - (t.get("createdAt") or 0)/1000 < 4*3600], key=lambda t: t["createdAt"])
    print(f"\n{dev[:8]} lanzamientos últimas 4 h: {len(rec)}")
    for t in rec:
        c0 = int(t["createdAt"]/1000)
        ch = requests.get(f"{B}/chart/{t['mint']}", headers=h, params={"type": "1s" , "time_from": c0 - 5, "time_to": c0 + 200}, timeout=30)
        if not ch.ok or not (ch.json().get("oclhv")):
            ch = requests.get(f"{B}/chart/{t['mint']}", headers=h, params={"type": "1m", "time_from": c0 - 60, "time_to": c0 + 1800}, timeout=30)
        cs = (ch.json().get("oclhv") or []) if ch.ok else []
        if not cs: print("   ", t.get("symbol"), "sin velas"); continue
        o = cs[0]["open"]; mx = max(x["high"] for x in cs); mn = min(x["low"] for x in cs); last = cs[-1]["close"]
        print(f"    {time.strftime('%H:%M', time.gmtime(c0-10800))} {t.get('symbol','')[:10]:<10} velas={len(cs)} ({'1s' if len(cs)>40 else '1m'}) apertura→ máx {mx/o:.2f}x  mín {mn/o:.2f}x  último {last/o:.2f}x | mcap ahora US${t.get('marketCapUsd') or 0:,.0f} | {t.get('market')}")
PY
