#!/bin/bash
# 30/10 — continuación de 188 (se quedó sin tiempo): k=4..6 con muestra de 220 eventos por configuración, compras ya descargadas.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections, random
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
def get(u):
    for i in range(4):
        try:
            r=requests.get(u,headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {}
        except Exception: time.sleep(1)
    return {}
buys=json.load(open("state/research/kolscan_buys_30d.json")); kol=json.load(open("state/research/kol_buys_30d.json")); now=time.time()
tygr=set(b["w"] for b in kol)
def trig(B,k,need_tygr=0):
    bym=collections.defaultdict(list)
    for b in B: bym[b["m"]].append(b)
    out=[]
    for m,bs in bym.items():
        bs.sort(key=lambda b:b["ts"]); seen={}
        for b in bs:
            seen.setdefault(b["w"],b["ts"])
            win=[w for w,t in seen.items() if b["ts"]-t<=3600]
            if len(win)>=k and sum(1 for w in win if w in tygr)>=need_tygr:
                if b["ts"]<now-7*3600: out.append((m,b["ts"]))
                break
    return sorted(out,key=lambda x:x[1])
def chart(m,t0):
    j=get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}")
    c=[x for x in (j.get("oclhv",[]) if isinstance(j,dict) else []) if x.get("time",0)>=t0-60]
    return c if len(c)>=3 and c[0]["close"]>0 and max(x["high"] for x in c)/c[0]["close"]<50 else None
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
RULES=[("TP2/SL30/6h",2,0.3,6,False),("50% a 2x, resto 30min",2,None,0.5,True),("50% a 2x, SL50, 30min",2,0.5,0.5,True)]
t0=time.time(); random.seed(11)
CONF=[("KOLSCAN 86",buys,4,0),("KOLSCAN 86",buys,6,0),("TODOS 107",buys+kol,4,0),("TODOS 107",buys+kol,6,0),("TODOS, >=2 del grupo TYGR",buys+kol,4,2)]
for tag,B,k,nt in CONF:
    T=trig(B,k,nt); samp=random.sample(T,min(220,len(T))); rows=[]
    for m,ts in samp:
        if time.time()-t0>540: break
        c=chart(m,ts); time.sleep(0.04)
        if c: rows.append(c)
    print(f"\n=== {tag} k={k}{' (>=2 TYGR)' if nt else ''}: eventos {len(T)}, muestra con velas {len(rows)} ===")
    if len(rows)<6: continue
    h=len(rows)//2
    for name,*r in RULES:
        for st,sub in (("todo",rows),("1.ª mitad",rows[:h]),("2.ª mitad",rows[h:])):
            v=[run(c,*r) for c in sub]
            print(f"  {name:24s} {st:9s} n={len(v):3d} acierto={sum(x>0 for x in v)/len(v):4.0%} prom={S.mean(v):+6.1%} mediana={S.median(v):+6.1%}")
print("OK")
PY
