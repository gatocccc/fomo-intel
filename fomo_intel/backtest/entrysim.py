"""Simulador de entradas sobre velas de 1 minuto (data/charts/).

Regla de oro: en cada decisión solo se usa lo que ya pasó. La etiqueta BUENO/MUERTO
no interviene en la entrada; sirve únicamente para mirar el resultado después.

Entrada: a `entry_min` minutos de la creación, en la primera vela que exista desde
ese momento (si no hay ninguna en los `max_wait_min` siguientes, no se entra).
Precio de compra = apertura de esa vela * (1 + slippage) * (1 + fee).
Salida (por orden de prioridad dentro de una misma vela, conservador: primero stop):
  - stop: low <= entrada * (1 - stop)
  - trailing: low <= máximo visto * (1 - trail)   (recién activo si el máximo superó la entrada)
  - take profit escalonado: high >= entrada*2 vende 50%; high >= entrada*4 vende 30% más
  - fin de datos: se vende el resto al último cierre (si la última vela es vieja, se asume
    que no hay liquidez y se castiga con `dead_haircut`).
Precio de venta = nivel * (1 - slippage) * (1 - fee).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SimParams:
    entry_min: int = 2
    max_wait_min: int = 3        # si no hay vela en esta ventana, no se entra
    latency_s: float = 1.5
    slippage: float = 0.05
    fee: float = 0.01
    stop: float = 0.35
    trail: float = 0.25
    tp_levels: tuple = ((2.0, 0.5), (4.0, 0.3))   # (múltiplo, fracción de la posición original)
    max_hold_min: int = 360
    dead_haircut: float = 0.5    # si al final no hay vela reciente, el resto se vende con este descuento
    fill: str = "close"          # precio de compra dentro de la vela de entrada: open | close | high
    stop_on: str = "low"         # low: la mecha toca el stop | close: el minuto cierra debajo del stop
    stop_fill: str = "level"     # level: se vende justo al nivel del stop (optimista) | close: al cierre de esa vela (realista: en un rug el precio salta)


@dataclass
class SimResult:
    mint: str
    symbol: str
    entered: bool
    reason: str = ""
    entry_t: int = 0
    entry_px: float = 0.0
    exits: list = field(default_factory=list)   # [(t, px, fraccion, motivo)]
    ret: float = 0.0                              # retorno neto sobre lo invertido (0.5 = +50%)
    hold_min: int = 0
    peak_mult: float = 0.0


def simulate(mint: str, symbol: str, created_ts: int, candles: list[dict], p: SimParams) -> SimResult:
    r = SimResult(mint=mint, symbol=symbol, entered=False)
    if not candles:
        r.reason = "sin velas"
        return r
    t_entry = created_ts + p.entry_min * 60 + int(p.latency_s)
    idx = next((i for i, c in enumerate(candles) if c["t"] >= t_entry), None)
    if idx is None or candles[idx]["t"] > t_entry + p.max_wait_min * 60:
        r.reason = "sin vela para entrar"
        return r
    c0 = candles[idx]
    base = {"open": c0["o"], "close": c0["c"], "high": c0["h"]}[p.fill]
    if base <= 0:
        r.reason = "vela de entrada sin precio"
        return r
    entry_px = base * (1 + p.slippage) * (1 + p.fee)
    r.entered, r.entry_t, r.entry_px = True, c0["t"], entry_px
    remaining = 1.0
    cash = 0.0
    peak = base
    tp_done = [False] * len(p.tp_levels)
    t_limit = c0["t"] + p.max_hold_min * 60
    last_t = c0["t"]

    def sell(frac, level, t, why):
        nonlocal remaining, cash
        frac = min(frac, remaining)
        if frac <= 0:
            return
        px = level * (1 - p.slippage) * (1 - p.fee)
        cash += frac * px / entry_px
        remaining -= frac
        r.exits.append((t, round(px, 10), round(frac, 2), why))

    for c in candles[idx + 1:]:
        if c["t"] > t_limit or remaining <= 1e-9:
            break
        last_t = c["t"]
        # la vela de entrada: solo se mira lo que pasa después de la apertura
        stop_lvl = entry_px * (1 - p.stop)
        ref = c["l"] if p.stop_on == "low" else c["c"]
        if ref <= stop_lvl:
            px_stop = min(stop_lvl, c["c"]) if (p.stop_on == "close" or p.stop_fill == "close") else stop_lvl
            sell(remaining, px_stop, c["t"], "stop")
            break
        if peak > entry_px and c["l"] <= peak * (1 - p.trail):
            sell(remaining, peak * (1 - p.trail), c["t"], "trailing")
            break
        for k, (mult, frac) in enumerate(p.tp_levels):
            if not tp_done[k] and c["h"] >= entry_px * mult:
                tp_done[k] = True
                sell(frac, entry_px * mult, c["t"], f"tp{mult:g}x")
        peak = max(peak, c["h"])
    if remaining > 1e-9:
        last = candles[min(len(candles) - 1, next(i for i, c in enumerate(candles) if c["t"] >= last_t))]
        stale = (candles[-1]["t"] - last_t) < 0 or True
        px = last["c"]
        why = "fin de datos"
        # si la historia terminó antes del límite de tenencia, el token dejó de operarse: liquidez dudosa
        if last["t"] < t_limit and last is candles[-1]:
            px *= (1 - p.dead_haircut)
            why = "sin liquidez"
        sell(remaining, px, last["t"], why)
    r.ret = round(cash - 1.0, 4)
    r.hold_min = (r.exits[-1][0] - r.entry_t) // 60 if r.exits else 0
    r.peak_mult = round(peak / entry_px, 2)
    return r


def summarize(results: list[SimResult]) -> dict:
    ent = [x for x in results if x.entered]
    if not ent:
        return {"entradas": 0}
    rets = [x.ret for x in ent]
    wins = [x for x in ent if x.ret > 0]
    return {
        "candidatos": len(results),
        "entradas": len(ent),
        "ganadoras": len(wins),
        "tasa_acierto": round(len(wins) / len(ent), 3),
        "retorno_medio": round(sum(rets) / len(rets), 3),
        "retorno_mediano": round(sorted(rets)[len(rets) // 2], 3),
        "peor": round(min(rets), 3),
        "mejor": round(max(rets), 3),
        "resultado_total_1usd_cada_una": round(sum(rets), 2),
        "motivos_salida": {m: sum(1 for x in ent for e in x.exits if e[3] == m) for m in sorted({e[3] for x in ent for e in x.exits})},
    }
