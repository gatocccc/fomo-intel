#!/bin/bash
# 31/10 00:45 — Grilla (vender volatilidad en rango) sobre SOL con velas de 1 min de Hyperliquid, 30 días.
# Regla: centro = media de 4 h; niveles cada STEP% (ATR-relativo); compra en cada nivel por debajo del centro, vende en cada nivel por
# encima; cada tramo cierra al volver al nivel anterior (gana STEP%). Apagado en tendencia: si el precio se aleja > KILL% del centro,
# cierra todo y espera a que vuelva a la banda. Costos: 0,06% por lado (Jupiter Perps) + 0,05% slippage. Tamaño: 1 tramo = 1 unidad.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 500 python3 - <<'PY'
import requests, time, statistics as S, json
def candles(coin, days):
    out=[]; end=int(time.time()*1000); start=end-days*86400*1000; t=start
    while t<end:
        r=requests.post("https://api.hyperliquid.xyz/info",json={"type":"candleSnapshot","req":{"coin":coin,"interval":"1m","startTime":t,"endTime":min(t+5000*60000,end)}},timeout=30).json()
        if not r: break
        out+=r; t=int(r[-1]["t"])+60000; time.sleep(0.2)
    return [(int(c["t"])//1000,float(c["o"]),float(c["h"]),float(c["l"]),float(c["c"])) for c in out]
FEE=0.0006+0.0005
def sim(cs, step, kill, center_n=240, max_levels=4):
    """Devuelve (pnl % sobre 1 unidad de capital por tramo*max_levels, nº cierres, nº kills, max drawdown)"""
    pnl=0.0; closes=0; kills=0; eq=[]; pos={}  # nivel -> precio de entrada (long si nivel<0, short si >0)
    peak=0; mdd=0
    for i in range(center_n, len(cs)):
        t,o,h,l,c=cs[i]
        center=S.fmean(x[4] for x in cs[i-center_n:i])
        dev=(c/center-1)
        if abs(dev)>kill:
            if pos:
                for lv,e in pos.items():
                    pnl+=((c/e-1) if lv<0 else (e/c-1))-FEE
                pos={}; kills+=1
            eq.append(pnl); continue
        lv=int(dev/step) if dev<0 else int(dev/step)
        if lv<0 and -lv<=max_levels and lv not in pos:   # por debajo: abrir largo en ese nivel
            pos[lv]=c
        if lv>0 and lv<=max_levels and lv not in pos:     # por encima: abrir corto
            pos[lv]=c
        # cerrar tramos que volvieron un nivel hacia el centro
        for k in list(pos):
            e=pos[k]
            if k<0 and c>=e*(1+step):  pnl+=(c/e-1)-FEE; closes+=1; del pos[k]
            if k>0 and c<=e*(1-step):  pnl+=(e/c-1)-FEE; closes+=1; del pos[k]
        # equity con no realizado
        u=sum(((c/e-1) if k<0 else (e/c-1)) for k,e in pos.items())
        eq.append(pnl+u); peak=max(peak,eq[-1]); mdd=min(mdd,eq[-1]-peak)
    return pnl, closes, kills, mdd, pos
for coin in ("SOL","ETH","BTC"):
    cs=candles(coin,30); n=len(cs)
    if n<5000: print(coin,"velas insuficientes",n); continue
    vol1m=S.pstdev([cs[i][4]/cs[i-1][4]-1 for i in range(1,n)])*100
    print(f"\n=== {coin}: {n} velas de 1 min (30 d), vol 1 min {vol1m:.3f}% ===")
    h=n//2
    for step in (0.004,0.006,0.008,0.012):
        for kill in (0.02,0.03,0.05):
            a=sim(cs[:h],step,kill); b=sim(cs[h:],step,kill); tot=sim(cs,step,kill)
            print(f"  paso {step*100:.1f}% kill {kill*100:.0f}%: 30 d pnl={tot[0]*100:+6.1f}% (sobre 1 tramo) cierres={tot[1]:4d} kills={tot[2]:3d} mdd={tot[3]*100:+5.1f}% | mitades {a[0]*100:+5.1f}% / {b[0]*100:+5.1f}%")
print("OK")
PY
