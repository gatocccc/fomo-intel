#!/bin/bash
# Hipótesis "post-graduación": comprar DESPUÉS de que el token migra a PumpSwap (liquidez real, sin dumps de curva),
# con filtros de calidad (velocidad hasta graduar, share de bots, concentración), y medir con velas de 6 h ya bajadas.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, itertools, statistics as st
from pathlib import Path
from fomo_intel.launches import LaunchFetcher
from fomo_intel.backtest.entrysim import SimParams, simulate
lf = LaunchFetcher("x", "data"); L = {l.mint: l for l in lf.load_all() if l.graduated}
rows = []
for m, l in L.items():
    raw = Path(f"data/launches_raw/{m}.json"); ch = Path(f"data/charts/{m}.json")
    if not raw.exists() or not ch.exists(): continue
    info = json.load(open(raw)); pools = info.get("pools") or []
    if len(pools) < 2: continue
    created = l.created_ts
    grad_ms = max(p.get("createdAt") or 0 for p in pools)          # el pool más nuevo = PumpSwap (migración)
    grad = int(grad_ms/1000) if grad_ms > 1e11 else int(grad_ms)
    if grad <= created or grad - created > 6*3600: continue
    candles = json.load(open(ch))["candles"]
    c_after = [c for c in candles if c["t"] >= grad]
    if len(c_after) < 5: continue
    fb = l.first_buyers; early = [b for b in fb if 0 <= b.first_trade_ts - created <= 120]
    bot_share = (sum(1 for b in early if b.tags) / len(early)) if early else None
    rows.append({"mint": m, "sym": l.symbol, "created": created, "grad": grad, "t_grad_min": round((grad-created)/60, 1), "candles": candles,
                 "top10": l.top10_pct, "dev_pct": l.dev_pct, "insider_pct": l.insider_pct, "bundler_pct": l.bundler_pct, "snipers": len(l.snipers),
                 "holders": l.holders, "bot_share": bot_share, "n_early": len(early), "rugged": l.rugged, "ret24": (l.returns.get("24h") or {}).get("chg")})
print(f"graduados con migración y velas posteriores: {len(rows)} ; tiempo hasta graduar mediana {st.median(r['t_grad_min'] for r in rows):.1f} min")
def run(sub, entry_delay_min, tp, trail, stop, hold, label):
    rets = []
    for r in sub:
        # entrada: primera vela >= grad + delay, al cierre; salida con stop realista
        p = SimParams(entry_min=0, max_wait_min=5, fill="close", stop_fill="close", tp_levels=((tp, 1.0),) if tp else (), trail=trail, stop=stop, max_hold_min=hold)
        s = simulate(r["mint"], r["sym"], r["grad"] + entry_delay_min*60, r["candles"], p)
        if s.entered: rets.append(s.ret)
    if len(rets) < 15: return None
    w = sum(1 for x in rets if x > 0)/len(rets)
    return (label, entry_delay_min, tp, trail, stop, hold, len(rets), round(w, 2), round(sum(rets)/len(rets), 3), round(min(rets), 2))
res = []
subsets = {"todos": rows,
           "rapidos(<=10min)": [r for r in rows if r["t_grad_min"] <= 10],
           "lentos(>10min)": [r for r in rows if r["t_grad_min"] > 10],
           "top10<=30%": [r for r in rows if r["top10"] and r["top10"] <= 30],
           "snipers<=5": [r for r in rows if r["snipers"] <= 5],
           "rapidos+top10<=30": [r for r in rows if r["t_grad_min"] <= 10 and r["top10"] and r["top10"] <= 30],
           "holders>=150": [r for r in rows if r["holders"] >= 150]}
for label, sub in subsets.items():
    print(f"\n== {label}: n={len(sub)}")
    out = []
    for delay, tp, trail, stop, hold in itertools.product((0, 2, 5, 10), (1.3, 1.5, 2.0, None), (0.15, 0.25, 0.4), (0.2, 0.3, 0.5), (60, 360)):
        r = run(sub, delay, tp, trail, stop, hold, label)
        if r: out.append(r)
    out.sort(key=lambda r: (-r[7], -r[8]))
    print("  por acierto (label, delay, tp, trail, stop, hold, n, acierto, ret/op, peor):")
    for r in out[:5]: print("   ", r[1:])
    pos = sorted([r for r in out if r[8] > 0], key=lambda r: -r[7])
    print("  con ret/op>0, por acierto:")
    for r in pos[:5]: print("   ", r[1:])
# precio final a 6 h vs precio de graduación (buy & hold)
bh = [r["candles"][-1]["c"] / [c for c in r["candles"] if c["t"] >= r["grad"]][0]["c"] for r in rows]
print(f"\nbuy&hold desde graduación hasta fin de datos: mediana {st.median(bh):.2f}x ; >1x en {sum(1 for x in bh if x>1)/len(bh):.0%} ; <0.5x en {sum(1 for x in bh if x<0.5)/len(bh):.0%}")
PY
