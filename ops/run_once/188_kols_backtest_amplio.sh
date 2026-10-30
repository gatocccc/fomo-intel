#!/bin/bash
# 30/10 — Backtest del consenso con lista AMPLIA: 86 KOLs del ranking de Kolscan (sin sesgo de TYGR) y 21+86 juntos.
# Gatillo = compra del k-ésimo KOL distinto en 60 min; entrada cierre de vela 1 min +3%; reglas de salida como en ops 184.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
SOLM={"So11111111111111111111111111111111111111112"}
ks=json.load(open("desk/research/kolscan_86.json"))
def get(u):
    for i in range(4):
        try:
            r=requests.get(u,headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {}
        except Exception: time.sleep(1)
    return {}
since=time.time()-30*86400; buys=[]; t0=time.time()
try: buys=json.load(open("state/research/kolscan_buys_30d.json"))
except Exception: pass
done=set(b["w"] for b in buys)
for w in ks:
    if w in done: continue
    if time.time()-t0>330: print("tiempo: corto la descarga en", len(done)); break
    cur=None; n=0
    for p in range(40):
        j=get(f"{ST}/wallet/{w}/trades"+(f"?cursor={cur}" if cur else "")); tr=j.get("trades",[]) if isinstance(j,dict) else []
        stop=False
        for t in tr:
            ts=t.get("time",0)/1000
            if ts<since: stop=True; break
            to=(t.get("to") or {}); fr=(t.get("from") or {})
            if fr.get("address") in SOLM and to.get("address") and to.get("address") not in SOLM:
                buys.append({"w":w,"m":to["address"],"ts":ts,"px":(t.get("price") or {}).get("usd") if isinstance(t.get("price"),dict) else t.get("price")}); n+=1
        cur=j.get("nextCursor") if isinstance(j,dict) else None
        if stop or not cur or not tr: break
    done.add(w); print(f"{ks[w]:14s} {n:5d}")
json.dump(buys,open("state/research/kolscan_buys_30d.json","w"))
print("descargadas", len(done), "de", len(ks), "compras", len(buys))
kol=json.load(open("state/research/kol_buys_30d.json"))
now=time.time()
def trig(B,k):
    bym=collections.defaultdict(list)
    for b in B: bym[b["m"]].append(b)
    out=[]
    for m,bs in bym.items():
        bs.sort(key=lambda b:b["ts"]); seen={}
        for b in bs:
            seen.setdefault(b["w"],b["ts"])
            if sum(1 for t in seen.values() if b["ts"]-t<=3600)>=k:
                if b["ts"]<now-7*3600: out.append((m,b["ts"]))
                break
    return sorted(out,key=lambda x:x[1])
C={}
def chart(m,t0):
    if (m,t0) in C: return C[(m,t0)]
    j=get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}")
    c=[x for x in (j.get("oclhv",[]) if isinstance(j,dict) else []) if x.get("time",0)>=t0-60]
    C[(m,t0)]=c if len(c)>=3 and c[0]["close"]>0 and max(x["high"] for x in c)/c[0]["close"]<50 else None
    return C[(m,t0)]
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
for tag,B in (("KOLSCAN 86",buys),("TODOS 107",buys+kol)):
    for k in (3,4,5,6):
        T=trig(B,k); rows=[]
        for m,ts in T:
            if time.time()-t0>540: break
            c=chart(m,ts); time.sleep(0.05)
            if c: rows.append(c)
        if len(rows)<6: print(f"\n{tag} k={k}: eventos {len(T)}, velas {len(rows)} (pocos)"); continue
        print(f"\n=== {tag} k={k}: eventos {len(T)}, con velas {len(rows)} ===")
        h=len(rows)//2
        for name,*r in RULES:
            for sub_tag,sub in (("todo",rows),("1.ª mitad",rows[:h]),("2.ª mitad",rows[h:])):
                v=[run(c,*r) for c in sub]
                print(f"  {name:24s} {sub_tag:9s} n={len(v):3d} acierto={sum(x>0 for x in v)/len(v):4.0%} prom={S.mean(v):+6.1%} mediana={S.median(v):+6.1%}")
print("OK")
PY
