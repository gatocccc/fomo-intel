#!/bin/bash
# ¿Por qué no detectamos lanzamientos de las fábricas? Comparar el "deployer" de ST con el creador que ve PumpPortal.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
for dev in json.load(open("state/factories.json"))["wallets"]:
    d = requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json(); toks = d.get("data") or []
    toks.sort(key=lambda t: -(t.get("createdAt") or 0))
    rec = [t for t in toks if now - (t.get("createdAt") or 0)/1000 < 8*3600]
    print(f"\n{dev} total={d.get('total')} creados en últimas 8 h: {len(rec)}")
    for t in toks[:2]:
        info = requests.get(f"{B}/tokens/{t['mint']}", headers=h, timeout=30).json()
        tk = info.get("token", {}); cr = tk.get("creation", {}); pools = info.get("pools") or [{}]
        print("   mint", t["mint"][:10], "hace", round((now - t['createdAt']/1000)/3600, 1), "h | item.creator:", str(t.get("creator"))[:12], "item.deployer:", str(t.get("deployer"))[:12], "| tokens.creation.creator:", str(cr.get("creator"))[:12], "pool.deployer:", str(pools[0].get("deployer"))[:12], "launchpad:", t.get("launchpad"), pools[0].get("market"))
PY
