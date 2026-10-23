#!/bin/bash
# Reputación de billeteras con los lanzamientos históricos: recurrencia en compras tempranas vs resultado del token.
# Split temporal: reputación con la primera mitad, prueba en la segunda mitad.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests, time
from collections import defaultdict
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import V1, base_price, entry_candle
lf = LaunchFetcher("x", "data"); L = [l for l in lf.load_all() if not l.partial and l.first_buyers]
toks = []
for l in L:
    cp = Path(f"data/charts/{l.mint}.json")
    if not cp.exists(): continue
    c = json.load(open(cp))["candles"]; t0 = l.created_ts
    bp = base_price(c)
    if not c or bp <= 0: continue
    # resultado "seguidor": entrar al minuto 1 (cuando compra la billetera buena), salida v1.2 con stop realista
    sim = simulate(l.mint, l.symbol, t0, c, SimParams(entry_min=1, fill="close", stop_fill="close", **V1["exit"]))
    if not sim.entered: continue
    last = c[-1]["c"]; final = last / sim.entry_px; peak = max(x["h"] for x in c if x["t"] >= t0 + 60) / sim.entry_px
    early = {b.wallet: (b.first_trade_ts - t0, b.invested_usd) for b in l.first_buyers if 0 <= b.first_trade_ts - t0 <= 120 and not b.is_developer}
    toks.append({"mint": l.mint, "sym": l.symbol, "t0": t0, "ret": sim.ret, "win": sim.ret > 0, "rug": final < 0.15, "peak": peak, "early": early, "dev": l.deployer})
toks.sort(key=lambda t: t["t0"])
print(f"tokens con velas y compradores: {len(toks)} ; acierto base (entrar min 1, salida v1.2): {sum(t['win'] for t in toks)/len(toks):.0%} ; rugs {sum(t['rug'] for t in toks)/len(toks):.0%}")
half = len(toks) // 2; train, test = toks[:half], toks[half:]
print(f"train {len(train)} tokens ({time.strftime('%d/%m', time.gmtime(train[0]['t0']))}–{time.strftime('%d/%m', time.gmtime(train[-1]['t0']))}), test {len(test)} ({time.strftime('%d/%m', time.gmtime(test[0]['t0']))}–{time.strftime('%d/%m', time.gmtime(test[-1]['t0']))})")
# reputación en train
stats = defaultdict(lambda: {"n": 0, "wins": 0, "rugs": 0, "peak2": 0})
for t in train:
    for w in t["early"]:
        s = stats[w]; s["n"] += 1; s["wins"] += t["win"]; s["rugs"] += t["rug"]; s["peak2"] += t["peak"] >= 2
rec = {w: s for w, s in stats.items() if s["n"] >= 3}
print(f"billeteras únicas en train: {len(stats)} ; recurrentes (>=3 tokens): {len(rec)}")
good = {w for w, s in rec.items() if s["wins"] / s["n"] >= 0.6 and s["rugs"] / s["n"] <= 0.2}
bad = {w for w, s in rec.items() if s["rugs"] / s["n"] >= 0.6}
print(f"buenas (>=60% ganados, <=20% rugs): {len(good)} ; tóxicas (>=60% rugs): {len(bad)}")
def ev(name, sel):
    g = [t for t in test if sel(t)]
    if not g: print(f"{name:<45} n=0"); return
    print(f"{name:<45} n={len(g):3d} acierto={sum(t['win'] for t in g)/len(g):.0%} rugs={sum(t['rug'] for t in g)/len(g):.0%} total={sum(t['ret'] for t in g):+.1f} ret/op={sum(t['ret'] for t in g)/len(g):+.2f}")
print("\n== PRUEBA en la segunda mitad (nunca vista) ==")
ev("todos", lambda t: True)
for k in (1, 2, 3):
    ev(f">= {k} billetera(s) buena(s) en los 120 s", lambda t, k=k: sum(1 for w in t["early"] if w in good) >= k)
    ev(f">= {k} buena(s) y ninguna tóxica", lambda t, k=k: sum(1 for w in t["early"] if w in good) >= k and not any(w in bad for w in t["early"]))
ev("alguna tóxica", lambda t: any(w in bad for w in t["early"]))
ev("ninguna tóxica", lambda t: not any(w in bad for w in t["early"]))
# cuántas de las buenas siguen activas en test
act = {w for t in test for w in t["early"]}
print(f"\nbuenas que reaparecen en test: {len(good & act)} de {len(good)} ; tóxicas que reaparecen: {len(bad & act)} de {len(bad)}")
# top recurrentes (todas las épocas) para consultar su PnL en Solana Tracker
allst = defaultdict(lambda: {"n": 0, "wins": 0, "rugs": 0})
for t in toks:
    for w in t["early"]:
        s = allst[w]; s["n"] += 1; s["wins"] += t["win"]; s["rugs"] += t["rug"]
top = sorted(((w, s) for w, s in allst.items() if s["n"] >= 4), key=lambda x: (-x[1]["wins"] / x[1]["n"], -x[1]["n"]))[:40]
print("\n== billeteras más recurrentes (>=4 tokens), ordenadas por % ganados ==")
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}
out = []
for w, s in top:
    pnl = {}
    try:
        r = requests.get(f"https://data.solanatracker.io/pnl/{w}", headers=h, params={"showHistoricPnL": "true", "hideDetails": "true"}, timeout=20)
        if r.ok:
            d = r.json(); sm = d.get("summary", d)
            pnl = {k: sm.get(k) for k in ("total", "totalInvested", "realized", "unrealized", "winPercentage", "lossPercentage", "totalWins", "totalLosses", "averageBuyAmount")}
    except Exception as e: pnl = {"err": str(e)[:80]}
    out.append({"wallet": w, **s, "st": pnl})
    print(f"  {w[:8]}… n={s['n']} ganados={s['wins']/s['n']:.0%} rugs={s['rugs']/s['n']:.0%}  ST: {json.dumps(pnl)[:160]}")
json.dump({"good": sorted(good), "bad": sorted(bad), "top": out}, open("state/ops/reputacion.json", "w"))
PY
