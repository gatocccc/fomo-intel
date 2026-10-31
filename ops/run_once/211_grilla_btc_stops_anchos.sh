#!/bin/bash
# 31/10 01:50 — BTC: stops anchos (4–8%) y tope de tiempo (12/24/48 h) desde la entrada. Grilla con la restricción real de Jupiter Perps (1 largo + 1 corto como máximo) e interés por hora. BTC/ETH/SOL, (vender volatilidad en rango) sobre SOL con velas de 1 min de Hyperliquid, 30 días.
# Regla: centro = media de 4 h; niveles cada STEP% (ATR-relativo); compra en cada nivel por debajo del centro, vende en cada nivel por
# encima; cada tramo cierra al volver al nivel anterior (gana STEP%). Apagado en tendencia: si el precio se aleja > KILL% del centro,
# cierra todo y espera a que vuelva a la banda. Costos: 0,06% por lado (Jupiter Perps) + 0,05% slippage. Tamaño: 1 tramo = 1 unidad.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 500 python3 - <<'PY'
import requests, time, statistics as S, json
def candles(coin, days):
    out=[]; end=int(time.time()*1000); t=end-days*86400*1000
    while t<end:
        r=requests.get("https://api.binance.com/api/v3/klines",params={"symbol":coin+"USDT","interval":"1m","startTime":t,"limit":1000},timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=r; t=int(r[-1][0])+60000; time.sleep(0.1)
    return [(int(c[0])//1000,float(c[1]),float(c[2]),float(c[3]),float(c[4])) for c in out]
FEE=0.0006*2+0.0005*2; BORROW_H=0.0001   # 0,06% apertura + 0,06% cierre + slippage; ~0,01%/h de interés (Jupiter Perps)
def sim(cs, step, kill, center_n=240, estop=None, tstop_h=None):
    pnl=0.0; closes=0; kills=0; eq=[]; pos={}   # lado -> (precio entrada, i apertura); max_levels=1: un largo y un corto como máximo
    peak=0; mdd=0; wins=0
    def pl(side,e,i0,c,i): return ((c/e-1) if side=="L" else (e/c-1))-FEE-BORROW_H*(i-i0)/60
    for i in range(center_n, len(cs)):
        t,o,h,l,c=cs[i]
        center=S.fmean(x[4] for x in cs[i-center_n:i]); dev=c/center-1
        if abs(dev)>kill:
            for sd,(e,i0) in pos.items(): pnl+=pl(sd,e,i0,c,i)
            if pos: kills+=1
            pos={}; eq.append(pnl); continue
        if dev<=-step and "L" not in pos: pos["L"]=(c,i)
        if dev>= step and "S" not in pos: pos["S"]=(c,i)
        for sd in list(pos):
            e,i0=pos[sd]
            if (estop and ((sd=="L" and c<=e*(1-estop)) or (sd=="S" and c>=e*(1+estop)))) or (tstop_h and i-i0>=tstop_h*60):
                pnl+=pl(sd,e,i0,c,i); closes+=1; kills+=1; del pos[sd]; continue
            if (sd=="L" and c>=e*(1+step)) or (sd=="S" and c<=e*(1-step)):
                r=pl(sd,e,i0,c,i); pnl+=r; closes+=1; wins+=r>0; del pos[sd]
        u=sum(pl(sd,e,i0,c,i) for sd,(e,i0) in pos.items())
        eq.append(pnl+u); peak=max(peak,eq[-1]); mdd=min(mdd,eq[-1]-peak)
    return pnl, closes, kills, mdd, wins
for coin in ("BTC",):
    cs=candles(coin,30); n=len(cs)
    if n<5000: print(coin,"velas insuficientes",n); continue
    vol1m=S.pstdev([cs[i][4]/cs[i-1][4]-1 for i in range(1,n)])*100
    print(f"\n=== {coin}: {n} velas de 1 min (30 d), vol 1 min {vol1m:.3f}% ===")
    h=n//2
    for center_n in (120,):
      for step in (0.008,):
        for estop,tstop in ((None,None),(0.04,None),(0.05,None),(0.06,None),(0.08,None),(None,12),(None,24),(None,48),(0.05,24),(0.06,48)):
            kill=0.03
            a=sim(cs[:h],step,kill,center_n,estop,tstop); b=sim(cs[h:],step,kill,center_n,estop,tstop); tot=sim(cs,step,kill,center_n,estop,tstop)
            print(f"  stop {estop and f'{estop*100:.0f}%' or 'no'} tiempo {tstop and f'{tstop}h' or 'no'}: 30 d pnl={tot[0]*100:+6.1f}% cierres={tot[1]:3d} acierto={tot[4]/max(tot[1],1):4.0%} stops={tot[2]:2d} mdd={tot[3]*100:+5.1f}% | mitades {a[0]*100:+5.1f}% / {b[0]*100:+5.1f}%")
print("OK")
PY
