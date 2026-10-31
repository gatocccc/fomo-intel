"""¿Si entran varias billeteras "buenas" al mismo token, es oportunidad? (idea de Gastón, 30/10/2026)

Diferencia con ops 182–189 (consenso de KOLs): ahí la lista se armó por nombre o por ranking de P&L del mes
(que incluye el período de prueba). Acá "buena" se define con datos, ANTES del período de prueba:

  Período A (primera mitad de los 30 días): por cada billetera, una muestra de sus compras; medimos cuánto
  subió el token 30 min después de que ella compró (desde su precio). Buena = n >= 12, media > 0 y t >= 1.
  Período B (segunda mitad): gatillo = la k-ésima billetera buena distinta compra el mismo token en <= 60 min.
  Entrada al cierre de la vela del gatillo +3% (nuestra demora), costos 4% ida y vuelta (memecoins, 30/10).

Controles en B: el mismo gatillo con billeteras NO buenas, y compras sueltas al azar (k=1) de cualquiera.
Datos: compras de 30 días de las 107 billeteras ya bajadas (state/research/kol*_buys_30d.json).
Salida: state/research/good_wallets.json y .log.
"""
from __future__ import annotations

import collections
import json
import math
import os
import random
import statistics as S
import time
from pathlib import Path

import requests

ST = "https://data.solanatracker.io"
SH = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
R = Path("state/research")
COST = 0.04
random.seed(7)


def get(u: str) -> dict:
    for i in range(4):
        try:
            r = requests.get(u, headers=SH, timeout=30)
            if r.status_code == 429:
                time.sleep(2 + 2 * i); continue
            return r.json() if r.status_code == 200 else {}
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return {}


_C: dict = {}


def chart(m: str, t0: float, secs: int) -> list | None:
    key = (m, int(t0) // 60, secs)
    if key in _C:
        return _C[key]
    j = get(f"{ST}/chart/{m}?type=1m&time_from={int(t0) - 60}&time_to={int(t0) + secs + 60}")
    c = [x for x in (j.get("oclhv", []) if isinstance(j, dict) else []) if x.get("time", 0) >= t0 - 60]
    ok = len(c) >= 3 and c[0]["close"] > 0 and max(x["high"] for x in c) / c[0]["close"] < 50
    _C[key] = c if ok else None
    time.sleep(0.04)
    return _C[key]


def stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    m = S.mean(xs); sd = S.pstdev(xs) if len(xs) > 1 else 0
    return {"n": len(xs), "win_pct": round(100 * sum(x > 0 for x in xs) / len(xs), 1), "mean_pct": round(100 * m, 2),
            "median_pct": round(100 * S.median(xs), 2), "t": round(m / (sd / math.sqrt(len(xs))), 2) if sd else None}


def rule(c: list, kind: str) -> float | None:
    e = c[0]["close"] * 1.03; t0 = c[0]["time"]
    if kind == "half2x_30m":      # 50% a 2x, resto a los 30 min, stop -50%
        tp, sl, hrs, half = 2, 0.5, 0.5, True
    elif kind == "tp2_sl30_6h":
        tp, sl, hrs, half = 2, 0.3, 6, False
    else:                          # hold 30 min
        tp, sl, hrs, half = 99, None, 0.5, False
    got = False
    win = [x for x in c if x["time"] <= t0 + hrs * 3600]
    if len(win) < 2:
        return None
    for x in win[1:]:
        if sl and x["low"] / e <= 1 - sl:
            return ((0.5 * (tp - 1) + 0.5 * -sl) if got else -sl) - COST
        if x["high"] / e >= tp:
            if not half:
                return tp - 1 - COST
            got = True
    last = win[-1]["close"] / e - 1
    return ((0.5 * (tp - 1) + 0.5 * last) if got else last) - COST


def triggers(B: list, k: int, now: float) -> list:
    bym = collections.defaultdict(list)
    for b in B:
        bym[b["m"]].append(b)
    out = []
    for m, bs in bym.items():
        bs.sort(key=lambda b: b["ts"]); seen: dict = {}
        for b in bs:
            seen.setdefault(b["w"], b["ts"])
            if sum(1 for t in seen.values() if b["ts"] - t <= 3600) >= k:
                if b["ts"] < now - 7 * 3600:
                    out.append((m, b["ts"]))
                break
    return sorted(out, key=lambda x: x[1])


def main() -> None:
    t_start = time.time()
    buys = []
    for f in ("kolscan_buys_30d.json", "kol_buys_30d.json"):
        try:
            buys += json.load(open(R / f))
        except Exception as e:  # noqa: BLE001
            print("falta", f, e)
    buys = [b for b in buys if b.get("px") and b.get("m") and b.get("ts")]
    t0, t1 = min(b["ts"] for b in buys), max(b["ts"] for b in buys)
    mid = (t0 + t1) / 2
    A = [b for b in buys if b["ts"] < mid]; Bp = [b for b in buys if b["ts"] >= mid]
    print(f"compras {len(buys)} · billeteras {len({b['w'] for b in buys})} · A {len(A)} · B {len(Bp)}", flush=True)

    # 1) calidad por billetera en A
    byw = collections.defaultdict(list)
    for b in A:
        byw[b["w"]].append(b)
    skill = {}
    for i, (w, bs) in enumerate(byw.items()):
        seen = set(); uniq = []
        for b in sorted(bs, key=lambda b: b["ts"]):
            if b["m"] not in seen:
                seen.add(b["m"]); uniq.append(b)
        sample = random.sample(uniq, min(30, len(uniq)))
        rets = []
        for b in sample:
            c = chart(b["m"], b["ts"], 1800)
            if not c:
                continue
            last = [x for x in c if x["time"] <= b["ts"] + 1800]
            if last and float(b["px"]) > 0:
                r = last[-1]["close"] / float(b["px"]) - 1
                if -1 < r < 20:
                    rets.append(r)
        s = stats(rets); s["buys_A"] = len(bs); s["buys_per_day"] = round(len(bs) / ((mid - t0) / 86400), 1)
        skill[w] = s
        if i % 10 == 0:
            print(f"  calidad {i}/{len(byw)} · {time.time() - t_start:.0f}s", flush=True)
    good = {w for w, s in skill.items() if s.get("n", 0) >= 12 and s["mean_pct"] > 0 and (s.get("t") or 0) >= 1}
    print(f"buenas {len(good)} de {len(skill)}", flush=True)

    # 2) gatillos en B
    res: dict = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "wallets": len(skill), "good": len(good),
                 "split_ts": mid, "skill": skill, "good_list": sorted(good), "tests": {}}
    Bg = [b for b in Bp if b["w"] in good]; Bn = [b for b in Bp if b["w"] not in good]
    half_ts = (mid + t1) / 2
    groups = [("buenas", Bg, k) for k in (2, 3, 4)] + [("no_buenas", Bn, k) for k in (2, 3, 4)]
    for name, src, k in groups:
        T = triggers(src, k, t1)
        if len(T) > 250:
            T = sorted(random.sample(T, 250), key=lambda x: x[1])
        rows = []
        for m, ts in T:
            if time.time() - t_start > 3000:
                break
            c = chart(m, ts, 6 * 3600)
            if c:
                rows.append((ts, c))
        out = {"events": len(T), "with_prices": len(rows)}
        for kind in ("half2x_30m", "tp2_sl30_6h", "hold_30m"):
            rs = [(ts, rule(c, kind)) for ts, c in rows]
            rs = [(ts, r) for ts, r in rs if r is not None]
            out[kind] = stats([r for _, r in rs])
            out[kind + "_mitad1"] = stats([r for ts, r in rs if ts < half_ts])
            out[kind + "_mitad2"] = stats([r for ts, r in rs if ts >= half_ts])
        res["tests"][f"{name}_k{k}"] = out
        print(f"{name} k={k}: {out['events']} eventos · " + " | ".join(f"{kk} {out[kk].get('mean_pct')}% n={out[kk].get('n')}" for kk in ("half2x_30m", "tp2_sl30_6h", "hold_30m")), flush=True)
    # azar: compras sueltas de cualquiera (k=1)
    rnd = random.sample(Bp, min(250, len(Bp)))
    rows = [c for b in rnd if (c := chart(b["m"], b["ts"], 6 * 3600))]
    res["tests"]["azar_k1"] = {k: stats([r for c in rows if (r := rule(c, k)) is not None]) for k in ("half2x_30m", "tp2_sl30_6h", "hold_30m")}
    print("azar k=1:", res["tests"]["azar_k1"], flush=True)
    json.dump(res, open(R / "good_wallets.json", "w"), indent=1)
    print("listo", round(time.time() - t_start), "s", flush=True)


if __name__ == "__main__":
    main()
