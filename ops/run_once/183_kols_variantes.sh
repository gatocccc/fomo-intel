#!/bin/bash
# 30/10 — Variantes del backtest de consenso de KOLs: salidas, cantidad de KOLs y mcap en el gatillo. Sin outliers rotos (>50x se descarta).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
ev=[e for e in json.load(open("state/research/kol_consenso_eventos.json")) if e["trigger_ts"]<time.time()-7*3600]
buys=json.load(open("state/research/kol_buys_30d.json"))
def chart(m,t0):
    for i in range(3):
        try:
            r=requests.get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}",headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json().get("oclhv",[]) if r.status_code==200 else []
        except Exception: time.sleep(1)
    return []
C={}
for e in ev:
    c=[x for x in chart(e["m"],e["trigger_ts"]) if x.get("time",0)>=e["trigger_ts"]-60]
    if len(c)>=3 and c[0]["close"]>0 and max(x["high"] for x in c)/c[0]["close"]<50: C[e["m"]]=c
    time.sleep(0.08)
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
def rep(tag,sub):
    if len(sub)<8: print(tag,"n<8"); return
    best=[]
    for tp in (1.3,1.5,2,3):
        for sl in (0.2,0.3,0.5,None):
            for hrs in (0.5,1,6):
                for half in (False,True):
                    v=[run(C[m],tp,sl,hrs,half) for m in sub]
                    best.append((S.mean(v),sum(x>0 for x in v)/len(v),S.median(v),tp,sl,hrs,half))
    best.sort(reverse=True)
    print(f"\n{tag} n={len(sub)}  mejores 4 salidas (prom, acierto, mediana, TP, SL, horas, mitad):")
    for b in best[:4]: print("   ", f"{b[0]:+.1%} {b[1]:.0%} {b[2]:+.1%}", b[3:])
    print("    peor:", f"{best[-1][0]:+.1%}", best[-1][3:])
evm={e["m"]:e for e in ev}
allm=[m for m in C]
rep("CONSENSO >=3 (todos)", allm)
rep("CONSENSO, 1.ª mitad", allm[:len(allm)//2]); rep("CONSENSO, 2.ª mitad", allm[len(allm)//2:])
rep(">=4 KOLs en total", [m for m in allm if evm[m]["n_total"]>=4])
rep("mcap gatillo < US$150K", [m for m in allm if (evm[m]["trigger_px"] or 0)*1e9<150_000])
rep("mcap gatillo >= US$150K", [m for m in allm if (evm[m]["trigger_px"] or 0)*1e9>=150_000])
print("OK")
PY
