#!/bin/bash
# 30/10 — Backtest paso 2: resultado de entrar (a) en la 1.ª compra de cualquier KOL y (b) en la 3.ª (consenso).
# Entrada = cierre de la vela de 1 min del gatillo +3% de costos. Salidas: A) TP 2x / SL -30% / 6 h. B) 50% a 2x (initials) + resto stop -30% o 6 h.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, random, requests, statistics as S
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
buys=json.load(open("state/research/kol_buys_30d.json")); ev=json.load(open("state/research/kol_consenso_eventos.json"))
first={}
for b in sorted(buys,key=lambda b:b["ts"]): first.setdefault(b["m"],b)
now=time.time()
single=[b for b in first.values() if b["ts"]<now-7*3600]
random.seed(7); single=random.sample(single,min(260,len(single)))
cons=[e for e in ev if e["trigger_ts"]<now-7*3600]
def chart(m,t0):
    for i in range(3):
        try:
            r=requests.get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}",headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            if r.status_code!=200: return []
            return r.json().get("oclhv",[])
        except Exception: time.sleep(1)
    return []
def sim(m,t0):
    c=chart(m,t0)
    c=[x for x in c if x.get("time",0)>=t0-60]
    if len(c)<3: return None
    e=c[0]["close"]*1.03
    if not e: return None
    A=None; B_half=False; B=None; mx=0
    for x in c[1:]:
        if x["time"]>t0+6*3600: break
        lo,hi=x["low"]/e,x["high"]/e; mx=max(mx,hi)
        if A is None:
            if lo<=0.70: A=-0.30
            elif hi>=2: A=1.0
        if B is None:
            if not B_half and hi>=2: B_half=True
            if lo<=0.70: B=(0.5*1.0+0.5*-0.30) if B_half else -0.30
    last=c[-1]["close"]/e-1
    if A is None: A=last
    if B is None: B=(0.5*1.0+0.5*last) if B_half else last
    return {"A":A,"B":B,"max":mx,"h2x":mx>=2}
def summ(tag,rows):
    rows=[r for r in rows if r]
    if not rows: print(tag,"sin datos"); return
    for k in ("A","B"):
        v=[r[k] for r in rows]
        print(f"{tag} salida {k}: n={len(v)} acierto={sum(x>0 for x in v)/len(v):.0%} prom={S.mean(v):+.1%} mediana={S.median(v):+.1%}")
    print(f"{tag} tocaron 2x: {sum(r['h2x'] for r in rows)/len(rows):.0%}  máx mediano: {S.median(r['max'] for r in rows):.2f}x")
t=time.time(); R1=[]; R3=[]
for e in cons: R3.append(sim(e["m"],e["trigger_ts"])); time.sleep(0.1)
print("consenso listo", round(time.time()-t))
for b in single:
    if time.time()-t>520: break
    R1.append(sim(b["m"],b["ts"])); time.sleep(0.1)
summ("CONSENSO (3 KOLs)",R3)
summ("CUALQUIER KOL (1.ª compra)",R1)
# mitad vieja vs nueva del consenso (fuera de muestra temporal)
h=len(R3)//2; summ("CONSENSO 1.ª mitad",R3[:h]); summ("CONSENSO 2.ª mitad",R3[h:])
json.dump({"cons":R3,"single":R1},open("state/research/kol_bt.json","w")); print("OK")
PY
