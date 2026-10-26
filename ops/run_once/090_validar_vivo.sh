#!/bin/bash
# Validación en vivo del cazador: resultado real (velas 1 s) de las decisiones en papel según su puntaje, entrando como lo haría en vivo.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import json, os, time, random, requests
from concurrent.futures import ThreadPoolExecutor
H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}
rows=[json.loads(l) for l in open("state/tweetsniper/decisions.jsonl")]
rows=[r for r in rows if time.time()-r["ts"]>200]
sc=sorted(r["score"] for r in rows)
q=lambda p: sc[int(len(sc)*p)]
print(f"decisiones: {len(rows)} | puntaje p50 {q(.5):.3f} p90 {q(.9):.3f} p99 {q(.99):.3f} máx {sc[-1]:.3f} | umbral 0.4223")
import statistics as st
print("vol_s1 vivo p50/p75/p90:", st.quantiles([r['vol_s1'] for r in rows],n=10)[4], st.quantiles([r['vol_s1'] for r in rows],n=10)[6], st.quantiles([r['vol_s1'] for r in rows],n=10)[8])
def sim(r, delay=1.5, slip=0.03, tp=1.0, stop=0.35, hold=80):
    t=r["ts"]+delay
    for i in range(3):
        try:
            cs=requests.get(f"https://data.solanatracker.io/chart/{r['mint']}",headers=H,params={"type":"1s","time_from":int(t)-2,"time_to":int(t)+hold+5},timeout=20).json().get("oclhv",[]); break
        except Exception: cs=[]; time.sleep(1)
    pre=[c for c in cs if c["time"]<=t]
    if not pre: return None
    px=float(pre[-1]["close"])*(1+slip)
    for c in cs:
        if c["time"]<=t: continue
        if float(c["low"])<=px*(1-stop): return -stop-0.02
        if float(c["high"])>=px*(1+tp): return tp-0.02
        if c["time"]>=t+hold: return float(c["close"])/px*0.98-1
    return float(cs[-1]["close"])/px*0.98-1
rows.sort(key=lambda r:-r["score"])
n=len(rows); random.seed(5)
buckets={"top 1%":rows[:max(10,n//100)],"top 1-3%":rows[max(10,n//100):n*3//100],"top 3-10%":random.sample(rows[n*3//100:n//10],min(60,n//10-n*3//100)),
         "resto (muestra)":random.sample(rows[n//10:],80)}
with ThreadPoolExecutor(8) as ex:
    for name,g in buckets.items():
        v=[x for x in ex.map(sim,g) if x is not None]
        if v: print(f"{name:16s} n={len(v):3d} acierto {sum(x>0 for x in v)/len(v):.0%} media {sum(v)/len(v):+.3f} mediana {sorted(v)[len(v)//2]:+.3f} | puntaje {g[-1]['score']:.3f}-{g[0]['score']:.3f}")
for r in rows[:12]: print("  ",r["symbol"],r["score"],r["vol_s1"],r["px_s1"],r["rank"],r["author"],r.get("tw_likes"))
PY
