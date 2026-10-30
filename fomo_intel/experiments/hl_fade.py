"""¿Ir en CONTRA de los traders top de Hyperliquid da ventaja? (30/10/2026, pregunta de Gastón tras hl_copy).

En hl_copy (ops 191–192) copiar al top del ranking dio −0,53% neto por operación (−0,34% bruto) → al revés daría +0,15%,
pero con 14 traders y t≈1,1. Acá: muestra grande del top (histórico y del mes), apalancamiento aproximado,
demora de 1 min en todas las operaciones de los últimos 20 días, mitades separadas y t por trader (no por operación).

- Pool: 300 con más ganancia histórica + 200 con más ganancia del mes (activas: volumen del mes ≥ US$300K, cuenta ≥ US$5K).
- Selección con días −60…−30 (fills propios); prueba en −30…0. Ir en contra = mismo momento, lado opuesto, salir cuando él sale.
- Costos 0,19% ida y vuelta. Apalancamiento aproximado = notional de la operación / valor de la cuenta hoy.

Uso: python -m fomo_intel.experiments.hl_fade   → state/research/hl_fade.json
"""
from __future__ import annotations

import json
import statistics as st
import sys
import time
from pathlib import Path

import requests

from fomo_intel.experiments import hl_copy as hc

OUT = Path("state/research/hl_fade.json")
NOW = hc.NOW
DAY = hc.DAY
T_DELAY = NOW - 20 * DAY
T_HALF = NOW - 15 * DAY
_c: dict = {}


def px_after(coin, t_ms):
    if coin not in _c:
        d, start = {}, int(T_DELAY - DAY)
        for _ in range(7):
            j = hc.post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m", "startTime": start, "endTime": int(NOW)}}) or []
            time.sleep(0.35)
            if not j:
                break
            for c in j:
                d[int(c["t"])] = float(c["c"])
            last = int(j[-1]["t"])
            if len(j) < 4000 or last >= NOW - 120000:
                break
            start = last + 60000
        _c[coin] = d
    return _c[coin].get((int(t_ms) // 60000 + 1) * 60000)


def summ(rets_by_trader):
    allr = [r for rs in rets_by_trader for r in rs]
    means = [st.mean(rs) for rs in rets_by_trader if rs]
    if not allr:
        return {"n": 0}
    out = {"traders": len(means), "n": len(allr), "mean_pct": round(100 * st.mean(allr), 3),
           "median_pct": round(100 * st.median(allr), 3), "win_pct": round(100 * sum(r > 0 for r in allr) / len(allr), 1),
           "traders_positive_pct": round(100 * sum(m > 0 for m in means) / len(means), 1),
           "mean_of_traders_pct": round(100 * st.mean(means), 3)}
    if len(means) > 2 and st.pstdev(means) > 0:
        out["t_by_trader"] = round(st.mean(means) / (st.stdev(means) / len(means) ** 0.5), 2)
    return out


def main():
    lb = requests.get(hc.LB, timeout=60).json().get("leaderboardRows", [])
    act = [r for r in lb if hc.perf(r, "month")[1] >= 3e5 and float(r.get("accountValue") or 0) >= 5e3]
    acct = {r["ethAddress"]: float(r.get("accountValue") or 0) for r in act}
    top_all = [r["ethAddress"] for r in sorted(act, key=lambda r: -hc.perf(r, "allTime")[0])[:300]]
    top_month = [r["ethAddress"] for r in sorted(act, key=lambda r: -hc.perf(r, "month")[0])[:200]]
    pool = list(dict.fromkeys(top_all + top_month))
    print("activas", len(act), "pool", len(pool), flush=True)

    traders, t0 = [], time.time()
    for i, a in enumerate(pool):
        if time.time() - t0 > 2100:
            print("corto por tiempo en", i, flush=True)
            break
        tr = hc.trades_from(hc.fills(a))
        ins = [t for t in tr if t["t0"] < hc.T_SPLIT]
        oos = [t for t in tr if t["t0"] >= hc.T_SPLIT and t["t1"] <= NOW - 120000]
        if len(ins) < 10 or len(oos) < 5:
            continue
        vol = sum(t["notional"] for t in ins)
        lev = st.median([t["notional"] for t in oos]) / acct[a] if acct.get(a) else None
        traders.append({"addr": a, "top_all": a in top_all, "top_month": a in top_month, "pnl_in": sum(t["pnl"] for t in ins),
                        "pnl_vol_in": sum(t["pnl"] for t in ins) / vol if vol else 0, "lev": lev, "oos": oos})
        if i % 50 == 0:
            print(f"  {i}/{len(pool)} útiles {len(traders)}", flush=True)
    print("útiles", len(traders), "— precios con demora…", flush=True)

    for t in traders:
        for o in t["oos"]:
            o["fade"] = -o["ret"] - hc.COST
            o["copy"] = o["ret"] - hc.COST
            if o["t0"] >= T_DELAY:
                a = px_after(o["coin"], o["t0"]); b = px_after(o["coin"], o["t1"])
                if a and b and o["t1"] > o["t0"] + 60000:
                    o["fade_d"] = -o["side"] * (b / a - 1) - hc.COST

    def cohort(name, cond):
        sel = [t for t in traders if cond(t)]
        g = lambda key, f=lambda o: True: [[o[key] for o in t["oos"] if key in o and f(o)] for t in sel]
        return {"cohort": name,
                "copiar": summ(g("copy")),
                "contra": summ(g("fade")),
                "contra_1a_mitad": summ(g("fade", lambda o: o["t0"] < T_HALF)),
                "contra_2a_mitad": summ(g("fade", lambda o: o["t0"] >= T_HALF)),
                "contra_misma_ventana_sin_demora": summ(g("fade", lambda o: "fade_d" in o)),
                "contra_con_demora_1min_20d": summ(g("fade_d")),
                "contra_ops_mas_de_30min": summ(g("fade_d", lambda o: o["t1"] - o["t0"] >= 30 * 60000))}

    res = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "pool": len(pool), "usable": len(traders),
           "cost_round_trip_pct": 100 * hc.COST, "cohorts": [
               cohort("todos (top histórico + top del mes)", lambda t: True),
               cohort("top histórico", lambda t: t["top_all"]),
               cohort("top del mes (en racha)", lambda t: t["top_month"]),
               cohort("venían ganando (−60…−30)", lambda t: t["pnl_in"] > 0),
               cohort("venían perdiendo (−60…−30)", lambda t: t["pnl_in"] <= 0),
               cohort("apalancamiento aprox. ≥ 5x", lambda t: (t["lev"] or 0) >= 5),
               cohort("apalancamiento aprox. < 2x", lambda t: t["lev"] is not None and t["lev"] < 2),
           ]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.exit(main())
