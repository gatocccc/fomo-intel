#!/bin/bash
# Historia COMPLETA de los creadores top vía Solana Tracker (/deployer/{wallet}): tasa real de graduación, actividad.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time
from collections import defaultdict
from fomo_intel.launches import LaunchFetcher
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
lf = LaunchFetcher("x", "data"); L = [l for l in lf.load_all() if l.deployer]
by = defaultdict(list)
for l in L: by[l.deployer].append(l)
cands = sorted(((sum(x.graduated for x in ls), len(ls), d) for d, ls in by.items() if sum(x.graduated for x in ls) >= 2), reverse=True)
print("creadores con >=2 graduados en nuestra muestra:", len(cands))
# formato del endpoint
d0 = cands[0][2]
r = requests.get(f"{B}/deployer/{d0}", headers=h, timeout=30); print("GET /deployer ->", r.status_code, r.text[:700])
out = []
now = time.time()
for g, n, dev in cands[:70]:
    try:
        r = requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30)
        if not r.ok: print(dev[:8], r.status_code); continue
        dj = r.json(); toks = dj.get("data") or dj.get("tokens") or []; total_api = dj.get("total")
    except Exception as e: print(dev[:8], "err", e); continue
    total = len(toks); grads = 0; recent = 0; last = 0; mcaps = []
    if toks and dev == cands[0][2]: print("campos de un token:", sorted(toks[0].keys()))
    for t in toks:
        created = t.get("createdAt") or t.get("created_time") or t.get("creation_time") or 0
        created = created/1000 if created > 1e11 else created
        last = max(last, created)
        if created and now - created < 7*86400: recent += 1
        market = (t.get("market") or "").lower()
        graduated = (market not in ("pumpfun", "pumpfun-curve", "pump", "")) or (t.get("curvePercentage") or 0) >= 100 or bool(t.get("graduated"))
        grads += graduated
        mcaps.append(t.get("marketCapUsd") or 0)
    row = {"dev": dev, "muestra_g": g, "muestra_n": n, "total_api": total_api, "total": total, "grads": grads, "rate": round(grads/total, 3) if total else None,
           "ultimos7d": recent, "ult_dias": round((now-last)/86400, 1) if last else None, "mcap_med": sorted(mcaps)[len(mcaps)//2] if mcaps else None}
    out.append(row)
    print(f"{dev[:10]}… muestra {g}/{n}  API total={total_api}  ult.{total}: grad {grads}/{total} = {row['rate']}  últimos7d={recent} último hace {row['ult_dias']} d  mcap med {row['mcap_med']}")
json.dump(out, open("state/ops/creadores_st.json", "w"), indent=1)
PY
