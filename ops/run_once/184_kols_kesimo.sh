#!/bin/bash
# 30/10 — Corrige sesgo de 183: ">=4 KOLs en total" miraba el futuro. Acá el gatillo ES la compra del k-ésimo KOL distinto (ventana 60 min).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
buys=json.load(open("state/research/kol_buys_30d.json")); now=time.time()
bym=collections.defaultdict(list)
for b in buys: bym[b["m"]].append(b)
def trig(k):
    out=[]
    for m,bs in bym.items():
        bs.sort(key=lambda b:b["ts"]); seen={}
        for b in bs:
            seen.setdefault(b["w"],b["ts"])
            if sum(1 for t in seen.values() if b["ts"]-t<=3600)>=k:
                if b["ts"]<now-7*3600 and not m.startswith("5wCqCq"): out.append((m,b["ts"],b["px"]))
                break
    return sorted(out,key=lambda x:x[1])
def chart(m,t0):
    for i in range(3):
        try:
            r=requests.get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}",headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json().get("oclhv",[]) if r.status_code==200 else []
        except Exception: time.sleep(1)
    return []
cache={}
def run(c,tp,sl,hrs,half):
    e=c[0]["close"]*1.03; t0=c[0]["time"]; got=False
    for x in c[1:]:
        if x["time"]>t0+hrs*3600: break
        if sl and x["low"]/e<=1-sl: return (0.5*(tp-1)+0.5*-sl) if got else -sl
        if x["high"]/e>=tp:
            if not half: return tp-1
            got=True
    last=[x for x in c if x["time"]<=t0+hrs*3600][-1]["close"]/e-1
    return (0.5*(tp-1)+0.5*last) if got else last
RULES=[("TP2 / SL30 / 6h",2,0.3,6,False),("50% a 2x, resto 30 min",2,None,0.5,True),("TP3 / sin SL / 30 min",3,None,0.5,False)]
t=time.time()
for k in (3,4,5):
    T=trig(k); rows=[]
    for m,ts,px in T:
        if time.time()-t>520: break
        key=(m,ts)
        c=[x for x in chart(m,ts) if x.get("time",0)>=ts-60]; time.sleep(0.08)
        if len(c)>=3 and c[0]["close"]>0 and max(x["high"] for x in c)/c[0]["close"]<50: rows.append(c)
    print(f"\n=== GATILLO = compra del KOL n.º {k} (eventos {len(T)}, con velas {len(rows)}) ===")
    h=len(rows)//2
    for name,*r in RULES:
        for tag,sub in (("todo",rows),("1.ª mitad",rows[:h]),("2.ª mitad",rows[h:])):
            if len(sub)<6: continue
            v=[run(c,*r) for c in sub]
            print(f"  {name:24s} {tag:9s} n={len(v):3d} acierto={sum(x>0 for x in v)/len(v):4.0%} prom={S.mean(v):+6.1%} mediana={S.median(v):+6.1%}")
print("OK")
PY
