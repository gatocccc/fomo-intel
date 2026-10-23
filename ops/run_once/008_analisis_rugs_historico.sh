#!/bin/bash
# Hipótesis anti-rug sobre los lanzamientos ya bajados: ¿qué separa a los que se vaciaron de los que vivieron?
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, statistics as stx
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
from fomo_intel.backtest.rules import V1, base_price, entry_candle
lf = LaunchFetcher("x", "data"); L = {l.mint: l for l in lf.load_all()}
charts = {p.stem: json.load(open(p))["candles"] for p in Path("data/charts").glob("*.json")}
rows = []
for m, l in L.items():
    c = charts.get(m)
    if not c or l.partial or not l.first_buyers: continue
    t0 = l.created_ts; bp = base_price(c); ec = entry_candle(c, t0, 2)
    if not ec or bp <= 0 or ec["c"] / bp < 3.0: continue            # solo los que pasaron el primer corte
    sim = simulate(m, l.symbol, t0, c, SimParams(entry_min=3, fill="close", stop_fill="close", **V1["exit"]))
    if not sim.entered: continue
    fb = sorted(l.first_buyers, key=lambda b: b.first_trade_ts)
    early = [b for b in fb if b.first_trade_ts - t0 <= 120]
    inv = sorted((b.invested_usd for b in early), reverse=True); tot = sum(inv) or 1
    dev = [b for b in fb if b.is_developer]
    last = c[-1]["c"]; final = last / sim.entry_px
    peak = max(x["h"] for x in c if x["t"] >= t0 + 180) / sim.entry_px
    rows.append({"sym": l.symbol, "ret": sim.ret, "rug": final < 0.15, "final": round(final, 2), "peak": round(peak, 2),
                 "n_early": len(early), "top1": round(inv[0] / tot, 2) if inv else 0, "top3": round(sum(inv[:3]) / tot, 2) if inv else 0,
                 "dev_inv": round(sum(b.invested_usd for b in dev), 0), "dev_share": round(sum(b.invested_usd for b in dev) / tot, 2),
                 "snipers": len(l.snipers), "sniper_pct": l.sniper_pct, "insider_pct": l.insider_pct, "bundlers": len(l.bundlers),
                 "early_tagged": sum(1 for b in early if b.tags), "vol_early": round(tot), "graduated": l.graduated})
print(f"tokens que pasaron el primer corte con compradores y velas: {len(rows)}; rugs (final < 0.15x): {sum(r['rug'] for r in rows)}; acierto v1.2-stop-realista: {sum(1 for r in rows if r['ret']>0)}/{len(rows)}")
def split(name, key, thr, op=">="):
    a = [r for r in rows if (r[key] >= thr if op == ">=" else r[key] < thr)]; b = [r for r in rows if r not in a]
    def desc(g):
        if not g: return "n=0"
        return f"n={len(g)} rugs={sum(r['rug'] for r in g)} acierto={sum(1 for r in g if r['ret']>0)/len(g):.0%} total={sum(r['ret'] for r in g):+.2f}"
    print(f"{name:<34} {op}{thr}: {desc(a)}   | resto: {desc(b)}")
for key, thr in (("top1", .25), ("top1", .35), ("top3", .5), ("top3", .6), ("dev_share", .1), ("dev_share", .2), ("sniper_pct", 10), ("sniper_pct", 20), ("insider_pct", 10), ("bundlers", 3), ("n_early", 40), ("n_early", 60), ("early_tagged", 3), ("peak", 1.3)):
    split(key, key, thr)
print("\nrugs:"); [print("  ", {k: r[k] for k in ("sym","final","top1","top3","dev_share","sniper_pct","insider_pct","bundlers","n_early","vol_early")}) for r in rows if r["rug"]]
print("\nganadoras (ret>0.3):"); [print("  ", {k: r[k] for k in ("sym","ret","peak","top1","top3","dev_share","sniper_pct","insider_pct","bundlers","n_early","vol_early")}) for r in rows if r["ret"] > 0.3]
json.dump(rows, open("state/ops/rug_rows.json", "w"))
PY
