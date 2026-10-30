#!/bin/bash
# 30/10 — Pregunta de Gastón: seguir a las billeteras privadas que compraron TYGR en los primeros segundos (no a las principales).
# 1) ¿Repiten? 30 días de trades de las billeteras de los 4 grupos con fondeo privado. 2) ¿Se las puede copiar? Entrada = vela de 1 s a +2 s de su compra (+3%), salida cuando ellas venden.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections, random
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
d=json.load(open("state/research/tygr_alts.json")); fund=d["funders"]
G={"B48kNV":"B48kNVXs4YK4amkBCH2XokQiv1SeiVQGHDR17xDeKAAn","8mowmV":"8mowmVCEewZ9W2cEaQyQeQEeSxhGr1hvRviLwozwNtBt","iGdFcQ":"iGdFcQoyR2MwbXMHQskhmNsqddZ6rinsipHc4TNSdwu","u6PJ8D":"u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w"}
W={w:g for g,f in G.items() for w,x in fund.items() if x==f}
print("billeteras por grupo:", collections.Counter(W.values()))
SOLM={"So11111111111111111111111111111111111111112"}
def get(u):
    for i in range(4):
        try:
            r=requests.get(u,headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {}
        except Exception: time.sleep(1)
    return {}
since=time.time()-30*86400; T=[]
for w,g in W.items():
    cur=None; n=0
    for p in range(15):
        j=get(f"{ST}/wallet/{w}/trades"+(f"?cursor={cur}" if cur else "")); tr=j.get("trades",[]) if isinstance(j,dict) else []
        stop=False
        for t in tr:
            ts=t.get("time",0)/1000
            if ts<since: stop=True; break
            fa=(t.get("from") or {}).get("address"); ta=(t.get("to") or {}).get("address")
            side="buy" if fa in SOLM else "sell" if ta in SOLM else None
            if side: T.append({"w":w,"g":g,"m":ta if side=="buy" else fa,"side":side,"ts":ts,"usd":(t.get("volume") or {}).get("usd") if isinstance(t.get("volume"),dict) else t.get("volume")}); n+=1
        cur=j.get("nextCursor") if isinstance(j,dict) else None
        if stop or not cur or not tr: break
    print(f"{g} {w[:6]} trades 30d: {n}")
bym=collections.defaultdict(list)
for t in T: bym[(t["w"],t["m"])].append(t)
pos=[]
for (w,m),ts in bym.items():
    b=[t for t in ts if t["side"]=="buy"]; s=[t for t in ts if t["side"]=="sell"]
    if b:
        b0=min(x["ts"] for x in b); s0=min([x["ts"] for x in s if x["ts"]>=b0] or [None]) if s else None
        pos.append({"w":w,"g":W[w],"m":m,"b":b0,"s":s0,"inv":sum(x["usd"] or 0 for x in b),"out":sum(x["usd"] or 0 for x in s)})
toks=collections.Counter(p["m"] for p in pos)
print(f"\nposiciones: {len(pos)}  tokens distintos: {len(toks)}  tokens con >=2 billeteras de los grupos: {sum(1 for c in toks.values() if c>=2)}")
for g in G:
    pp=[p for p in pos if p["g"]==g]
    if not pp: continue
    hold=[p["s"]-p["b"] for p in pp if p["s"]]
    win=[p for p in pp if p["out"]>p["inv"]]
    print(f"{g}: posiciones {len(pp)}  ganadoras {len(win)/len(pp):.0%}  invertido US${sum(p['inv'] for p in pp):.0f}  retirado US${sum(p['out'] for p in pp):.0f}  tenencia mediana {S.median(hold) if hold else 0:.0f} s  vende <60 s: {sum(h<60 for h in hold)/max(1,len(hold)):.0%}")
# copia con 2 s de demora
def c1s(m,a,b):
    j=get(f"{ST}/chart/{m}?type=1s&time_from={int(a)}&time_to={int(b)}"); return j.get("oclhv",[]) if isinstance(j,dict) else []
random.seed(3); samp=random.sample([p for p in pos if p["s"]],min(120,len([p for p in pos if p["s"]])))
R=[]; t0=time.time()
for p in samp:
    if time.time()-t0>300: break
    c=c1s(p["m"],p["b"]-2,p["s"]+10)
    if len(c)<2: continue
    ent=[x for x in c if x["time"]>=p["b"]+2]; ext=[x for x in c if x["time"]>=p["s"]+2]
    if not ent or not ext: continue
    their_in=[x for x in c if x["time"]<=p["b"]] or c[:1]
    e=ent[0]["close"]*1.03; x=ext[0]["close"]*0.97
    R.append({"copia":x/e-1,"ellos":ext[0]["close"]/their_in[-1]["close"]-1,"salto_entrada":ent[0]["close"]/their_in[-1]["close"]-1})
    time.sleep(0.05)
if R:
    v=[r["copia"] for r in R]
    print(f"\nCOPIA a +2 s (n={len(R)}): acierto {sum(x>0 for x in v)/len(v):.0%}  prom {S.mean(v):+.1%}  mediana {S.median(v):+.1%}")
    print(f"ellos mismos (precio de su vela): mediana {S.median(r['ellos'] for r in R):+.1%}; el precio ya subió entre su compra y nuestra entrada: mediana {S.median(r['salto_entrada'] for r in R):+.1%}")
print("OK")
PY
