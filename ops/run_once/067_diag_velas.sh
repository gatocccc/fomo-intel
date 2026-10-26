#!/bin/bash
# ¿Las velas terminan porque el token murió o porque la API corta la serie? Distribución de velas, último minuto vs entrada, mcap actual.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u - <<'PY' 9>&-
import json, statistics as st, os, requests, time
from collections import Counter
from pathlib import Path
D = Path("data/exp_red")
for u, entry in (("bags", 60), ("pump", 3)):
    rows = [json.loads(l) for l in open(D / f"{u}_tokens.jsonl")]
    n = [r["n_candles"] for r in rows]
    print(f"\n== {u}: tokens {len(rows)} | velas: mediana {st.median(n)}, p90 {sorted(n)[int(.9*len(n))]}, max {max(n)} | con 0 velas: {sum(1 for x in n if x==0)} | >=1000: {sum(1 for x in n if x>=1000)}")
    span = []; alive = 0
    for r in rows:
        cs = json.load(open(D / "charts" / f"{r['mint']}.json"))["m1"]
        if len(cs) < 3: continue
        last_min = (cs[-1]["t"] - r["created"]) / 60
        span.append(last_min)
        if last_min >= entry: alive += 1
    print(f"   último minuto con velas desde la creación: mediana {st.median(span):.0f} min, p75 {sorted(span)[int(.75*len(span))]:.0f}, p90 {sorted(span)[int(.9*len(span))]:.0f} | con velas más allá del minuto {entry}: {alive}")
    mc = [r["mcap_now"] or 0 for r in rows]
    print(f"   mcap actual: >=US$10K: {sum(1 for x in mc if x>=1e4)}, >=US$50K: {sum(1 for x in mc if x>=5e4)}, >=US$100K: {sum(1 for x in mc if x>=1e5)}, >=US$1M: {sum(1 for x in mc if x>=1e6)} | status: {Counter(r['status'] for r in rows).most_common(5)}")
    # chequeo directo: un token con muchas velas, ¿la API corta en N?
    big = max(rows, key=lambda r: r["n_candles"])
    h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}
    for hours in (6, 12, 48):
        d = requests.get(f"https://data.solanatracker.io/chart/{big['mint']}", headers=h, params={"type": "1m", "time_from": big["created"] - 60, "time_to": big["created"] + hours * 3600}, timeout=30).json()
        print(f"   {big['symbol']} velas 1m pidiendo {hours} h: {len(d.get('oclhv', []))}")
        time.sleep(0.3)
    # tokens de bags que hoy valen >= US$100K: ¿tenían velas a los 60 min? ¿cuál era el precio al min 60 vs ahora?
    if u == "bags":
        for r in sorted(rows, key=lambda r: -(r["mcap_now"] or 0))[:12]:
            cs = json.load(open(D / "charts" / f"{r['mint']}.json"))["m1"]
            c60 = next((c for c in cs if c["t"] >= r["created"] + 3600), None)
            print(f"   top: {r['symbol']:<10} mcap_now {r['mcap_now']:>12,.0f} velas {len(cs):4d} min_ult {((cs[-1]['t']-r['created'])/60 if cs else 0):6.0f} precio@60min {c60['c'] if c60 else None} max_post {max((c['h'] for c in cs if c60 and c['t']>c60['t']), default=0)} socials {r['socials']} creador_prev {len((r.get('dev_hist') or {}).get('prior', []))}")
PY
