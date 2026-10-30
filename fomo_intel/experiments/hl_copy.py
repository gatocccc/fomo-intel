"""¿Sirve copiar a traders rentables de perps? (30/10/2026, pedido de Gastón tras ver un "Trader rentable" en Phantom).

Phantom y FOMO ejecutan sus perps en Hyperliquid, así que el historial de cualquier billetera es público (API /info).

Protocolo (el mismo del 25/10: elegir con el pasado, medir en el futuro):
- Pool: billeteras activas del ranking público de Hyperliquid (volumen del mes ≥ US$300K, cuenta ≥ US$5K):
  las 150 de más ganancia histórica + 150 al azar (control de sesgo de selección).
- Fills de los últimos 60 días. Se arma cada operación (de posición 0 a posición 0) por mercado.
- Selección con los días −60…−30: acierto, ganancia/volumen (closedPnl / notional), n.º de operaciones.
- Prueba con los días −30…0: retorno de copiar cada operación (sin apalancamiento, igual peso por operación) a los precios
  del trader menos costos (taker 0,045% + slippage 0,05% por lado). Cota optimista.
- Demora real: para operaciones de los últimos 3 días se recalcula con velas de 1 min, entrando y saliendo al cierre del
  minuto siguiente (≈30–90 s de atraso, lo que tarda un seguidor).
- Además busca al trader de la captura (OP 3x largo, entrada 0,11678; histórico ~US$113K sobre ~US$97M).

Uso: python -m fomo_intel.experiments.hl_copy   → state/research/hl_copy.json
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

API = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
OUT = Path("state/research/hl_copy.json")
COST = 2 * (0.00045 + 0.0005)
NOW = time.time() * 1000
DAY = 86400 * 1000
T_SPLIT = NOW - 30 * DAY
T_START = NOW - 60 * DAY
T_RECENT = NOW - 3 * DAY


def post(body, tries=5):
    for i in range(tries):
        try:
            r = requests.post(API, json=body, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(4 + 4 * i)
                continue
        except Exception as e:  # noqa: BLE001
            print("  err", body.get("type"), e, flush=True)
        time.sleep(1 + i)
    return None


def perf(row, win):
    for w, d in row.get("windowPerformances", []):
        if w == win:
            return float(d.get("pnl") or 0), float(d.get("vlm") or 0)
    return 0.0, 0.0


def fills(addr):
    out, start = [], int(T_START)
    for _ in range(6):
        j = post({"type": "userFillsByTime", "user": addr, "startTime": start, "aggregateByTime": True})
        time.sleep(0.6)
        if not j:
            break
        out += j
        if len(j) < 2000:
            break
        start = int(j[-1]["time"]) + 1
    return out


def trades_from(fs):
    """Operaciones completas: desde que la posición sale de 0 hasta que vuelve a 0 (o se da vuelta)."""
    by = defaultdict(list)
    for f in fs:
        if f.get("coin", "").startswith("@"):
            continue  # spot
        by[f["coin"]].append(f)
    res = []
    for coin, lst in by.items():
        lst.sort(key=lambda f: f["time"])
        cur = None
        for f in lst:
            sz = float(f["sz"]); px = float(f["px"]); start = float(f["startPosition"])
            sgn = 1 if f["side"] == "B" else -1
            end = start + sgn * sz
            if cur is None and start == 0 and end != 0:
                cur = {"coin": coin, "side": 1 if end > 0 else -1, "t0": f["time"], "in_n": 0.0, "in_q": 0.0,
                       "out_n": 0.0, "out_q": 0.0, "pnl": 0.0, "fee": 0.0}
            if cur is None:
                continue
            opening = (sgn == cur["side"])
            if opening:
                cur["in_n"] += sz * px; cur["in_q"] += sz
            else:
                q = min(sz, abs(start)) if start != 0 else sz
                cur["out_n"] += q * px; cur["out_q"] += q
            cur["pnl"] += float(f.get("closedPnl") or 0); cur["fee"] += float(f.get("fee") or 0)
            if end == 0 or (start != 0 and (end > 0) != (start > 0)):
                if cur["in_q"] > 0 and cur["out_q"] > 0:
                    pin = cur["in_n"] / cur["in_q"]; pout = cur["out_n"] / cur["out_q"]
                    cur.update(t1=f["time"], pin=pin, pout=pout, ret=cur["side"] * (pout / pin - 1), notional=cur["in_n"])
                    res.append(cur)
                cur = None
                if end != 0:  # se dio vuelta: arranca una nueva con el resto
                    cur = {"coin": coin, "side": 1 if end > 0 else -1, "t0": f["time"], "in_n": abs(end) * px,
                           "in_q": abs(end), "out_n": 0.0, "out_q": 0.0, "pnl": 0.0, "fee": 0.0}
    return res


_candles: dict = {}


def px_after(coin, t_ms):
    """Cierre del minuto siguiente al evento (≈30–90 s de demora)."""
    if coin not in _candles:
        j = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m", "startTime": int(T_RECENT - DAY), "endTime": int(NOW)}}) or []
        _candles[coin] = {int(c["t"]): float(c["c"]) for c in j}
        time.sleep(0.4)
    m = (int(t_ms) // 60000 + 1) * 60000
    return _candles[coin].get(m)


def stats(rets):
    if not rets:
        return {"n": 0}
    m = st.mean(rets); sd = st.pstdev(rets) if len(rets) > 1 else 0
    return {"n": len(rets), "mean_pct": round(100 * m, 3), "median_pct": round(100 * st.median(rets), 3),
            "win_pct": round(100 * sum(r > 0 for r in rets) / len(rets), 1),
            "t": round(m / (sd / len(rets) ** 0.5), 2) if sd > 0 else None}


def main():
    lb = requests.get(LB, timeout=60).json().get("leaderboardRows", [])
    print("ranking:", len(lb), "billeteras", flush=True)

    # 1) el trader de la captura
    cand = []
    for r in lb:
        p, v = perf(r, "allTime")
        if 60e6 <= v <= 140e6 and 70e3 <= p <= 170e3:
            cand.append(r["ethAddress"])
    found = []
    for a in cand[:80]:
        s = post({"type": "clearinghouseState", "user": a}) or {}
        time.sleep(0.4)
        for ap in s.get("assetPositions", []):
            pos = ap.get("position", {})
            if pos.get("coin") == "OP" and float(pos.get("szi") or 0) > 0:
                found.append({"addr": a, "entry": pos.get("entryPx"), "lev": pos.get("leverage"), "value": pos.get("positionValue")})
    print("candidatos por volumen/ganancia:", len(cand), "| con OP largo ahora:", found, flush=True)

    # 2) pool
    act = []
    for r in lb:
        p, v = perf(r, "month")
        if v >= 3e5 and float(r.get("accountValue") or 0) >= 5e3:
            act.append(r)
    top = sorted(act, key=lambda r: -perf(r, "allTime")[0])[:150]
    rest = [r for r in act if r not in top]
    random.seed(30)
    rnd = random.sample(rest, min(150, len(rest)))
    pool = [(r["ethAddress"], "top") for r in top] + [(r["ethAddress"], "rnd") for r in rnd] + [(f["addr"], "screenshot") for f in found]
    print("pool:", len(pool), "de", len(act), "activas", flush=True)

    traders = []
    t_begin = time.time()
    for i, (a, src) in enumerate(pool):
        if time.time() - t_begin > 2400:
            print("corto por tiempo en", i, flush=True)
            break
        tr = trades_from(fills(a))
        ins = [t for t in tr if t["t0"] < T_SPLIT]
        oos = [t for t in tr if t["t0"] >= T_SPLIT]
        if len(ins) < 10 or len(oos) < 5:
            continue
        vol = sum(t["notional"] for t in ins)
        traders.append({"addr": a, "src": src, "n_in": len(ins), "win_in": sum(t["pnl"] > 0 for t in ins) / len(ins),
                        "pnl_vol_in": sum(t["pnl"] for t in ins) / vol if vol else 0, "pnl_in": sum(t["pnl"] for t in ins),
                        "oos": [{k: t[k] for k in ("coin", "side", "t0", "t1", "pin", "pout", "ret", "pnl")} for t in oos[:400]]})
        if i % 25 == 0:
            print(f"  {i}/{len(pool)} útiles {len(traders)}", flush=True)

    def cohort(name, cond):
        sel = [t for t in traders if cond(t)]
        rets, rets_tr, delayed, own = [], [], [], []
        for t in sel:
            rs = [o["ret"] - COST for o in t["oos"]]
            rets += rs
            rets_tr.append(st.mean(rs))
            for o in t["oos"]:
                if o["t0"] >= T_RECENT and o["t1"] <= NOW - 120000:
                    a = px_after(o["coin"], o["t0"]); b = px_after(o["coin"], o["t1"])
                    if a and b:
                        delayed.append(o["side"] * (b / a - 1) - COST)
                        own.append(o["ret"] - COST)
        return {"cohort": name, "traders": len(sel), "per_trade": stats(rets),
                "per_trader_positive_pct": round(100 * sum(x > 0 for x in rets_tr) / len(rets_tr), 1) if rets_tr else None,
                "per_trader_mean_pct": round(100 * st.mean(rets_tr), 3) if rets_tr else None,
                "last3d_own_prices": stats(own), "last3d_with_delay": stats(delayed)}

    res = {
        "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "screenshot_match": found,
        "cost_round_trip_pct": 100 * COST, "traders_usable": len(traders),
        "cohorts": [
            cohort("todos", lambda t: True),
            cohort("azar (control)", lambda t: t["src"] == "rnd"),
            cohort("ranking top", lambda t: t["src"] == "top"),
            cohort("ganadores pasado (pnl>0)", lambda t: t["pnl_in"] > 0),
            cohort("tipo captura: acierto≥80% y pnl/vol<0,3%", lambda t: t["win_in"] >= 0.8 and 0 < t["pnl_vol_in"] < 0.003),
            cohort("ventaja: pnl/vol≥1% y ≥10 ops", lambda t: t["pnl_vol_in"] >= 0.01),
            cohort("ventaja fuerte: pnl/vol≥2%", lambda t: t["pnl_vol_in"] >= 0.02),
            cohort("captura", lambda t: t["src"] == "screenshot"),
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    slim = dict(res)
    OUT.write_text(json.dumps(slim, indent=1))
    Path("state/research/hl_copy_traders.json").write_text(json.dumps(traders))
    print(json.dumps(res, indent=1, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.exit(main())
