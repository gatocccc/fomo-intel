#!/bin/bash
# Verdad de campo: lanzamientos reales de las 3 fábricas desde el inicio de la sesión vs lo que vio el bot.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 200 python3 -u - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
start = json.load(open("state/session.json"))["start"]
cr = json.load(open("state/creators.json")) if os.path.exists("state/creators.json") else {}
print("creadores registrados en vivo:", len(cr), "| creaciones totales registradas:", sum(len(v) for v in cr.values()))
for dev in json.load(open("state/factories.json"))["wallets"]:
    d = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    rec = sorted([t for t in d if (t.get("createdAt") or 0)/1000 >= start], key=lambda t: t["createdAt"])
    last = max((t.get("createdAt") or 0) for t in d)/1000 if d else 0
    print(f"\n{dev[:8]}: lanzó {len(rec)} desde las 14:59 | último lanzamiento hace {(now-last)/3600:.1f} h | vistos por el bot: {len([x for x in cr.get(dev, []) if x >= start])}")
    for t in rec[:10]: print("   ", time.strftime('%H:%M', time.gmtime(t['createdAt']/1000 - 3*3600)), "ART", t.get("symbol"), t["mint"][:10], "mcap", round(t.get("marketCapUsd") or 0))
s = json.load(open("state/live_summary.json")); print("\nhelius:", s.get("helius"), "| stream:", s.get("stream_connected"), "| tokens vistos:", s.get("tokens_seen"))
PY
journalctl -u fomo-live --since "-100 min" --no-pager | grep -E "FABRICA|COMPRA|HELIUS create|ERROR|Traceback" | tail -10
