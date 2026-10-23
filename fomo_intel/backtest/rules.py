"""Reglas de entrada medibles a los N minutos del lanzamiento (sin mirar el futuro).

Cada regla devuelve True si el token PASA. `evaluate` calcula todas y devuelve
un diccionario de resultados por regla más los números crudos para auditar.
"""
from __future__ import annotations

from collections import defaultdict

FACTORIES_BLACKLIST = {"6LpRMG", "3dU6Mz"}   # prefijos de deployers fábrica detectados en el análisis previo


def base_price(candles: list[dict]) -> float:
    """Precio base de la curva: apertura de la primera vela con precio."""
    for c in candles:
        if c["o"] > 0:
            return c["o"]
    return 0.0


def entry_candle(candles: list[dict], created_ts: int, entry_min: int, max_wait_min: int = 3):
    t = created_ts + entry_min * 60
    for c in candles:
        if c["t"] >= t:
            return c if c["t"] <= t + max_wait_min * 60 else None
    return None


def build_context(launches: dict) -> dict:
    """Datos del universo que un bot tendría acumulados: símbolos ya vistos y historial por deployer."""
    by_symbol = defaultdict(list)
    by_dev = defaultdict(list)
    for L in launches.values():
        by_symbol[L.symbol.strip().lower()].append((L.created_ts, L.mint))
        if L.deployer:
            by_dev[L.deployer].append((L.created_ts, L.graduated))
    return {"by_symbol": by_symbol, "by_dev": by_dev}


def features(L, candles: list[dict], ctx: dict, entry_min: int = 2) -> dict:
    t0 = L.created_ts
    ec = entry_candle(candles, t0, entry_min)
    bp = base_price(candles)
    fb = sorted(L.first_buyers, key=lambda b: b.first_trade_ts)
    n60 = len({b.wallet for b in fb if 0 <= b.first_trade_ts - t0 <= 60})
    n120 = len({b.wallet for b in fb if 0 <= b.first_trade_ts - t0 <= entry_min * 60})
    sym = L.symbol.strip().lower()
    prior_same_symbol = sum(1 for ts, m in ctx["by_symbol"].get(sym, []) if ts < t0 and m != L.mint)
    prior_dev = [(ts, g) for ts, g in ctx["by_dev"].get(L.deployer, []) if ts < t0]
    prior_dev_launches = len(prior_dev)
    prior_dev_grads = sum(1 for _, g in prior_dev if g)
    vol120 = sum(c["v"] for c in candles if 0 <= c["t"] - t0 <= entry_min * 60)
    return {
        "entry_px": ec["c"] if ec else None,
        "move_vs_base": (ec["c"] / bp) if (ec and bp > 0) else None,
        "pumpfun": L.launchpad == "pumpfun",
        "mint_pump_suffix": L.mint.endswith("pump"),
        "prior_same_symbol": prior_same_symbol,
        "dev_prefix": L.deployer[:6],
        "prior_dev_launches": prior_dev_launches,
        "prior_dev_grads": prior_dev_grads,
        "sniper_pct": L.sniper_pct,
        "n_bundlers": len(L.bundlers),
        "n_snipers": len(L.snipers),
        "n_buyers_60s": n60,
        "n_buyers_entry": n120,
        "dev_in_first10": any(b.is_developer for b in fb[:10]),
        "vol_usd_entry": round(vol120, 0),
    }


RULES = {
    # descarte
    "R1_se_movio":        lambda f: f["move_vs_base"] is not None and f["move_vs_base"] >= 1.3,
    "R2_pumpfun_sufijo":  lambda f: f["pumpfun"] and f["mint_pump_suffix"],
    "R3_no_copia":        lambda f: f["prior_same_symbol"] == 0,
    "R4_dev_limpio":      lambda f: f["dev_prefix"] not in FACTORIES_BLACKLIST and not (f["prior_dev_launches"] >= 2 and f["prior_dev_grads"] == 0),
    "R5_sin_snipers":     lambda f: f["sniper_pct"] <= 20 and f["n_bundlers"] <= 3,
    # a favor
    "R7_compradores":     lambda f: f["n_buyers_entry"] >= 8 and f["n_buyers_entry"] >= f["n_buyers_60s"],
    "R8_dev_compro":      lambda f: f["dev_in_first10"],
    "R11_volumen":        lambda f: f["vol_usd_entry"] >= 2000,
}


def evaluate(f: dict) -> dict:
    return {k: bool(fn(f)) for k, fn in RULES.items()}


# ---------- regla v1 congelada (22/10/2026) ----------
V1 = {"min_move": 3.0, "min_buyers": 40, "min_vol_usd": 2000, "min_snipers": 1, "entry_min": 2,
      "exit": {"tp_levels": ((2.0, 0.5),), "trail": 0.20, "stop": 0.30}}


def rule_v1(f: dict) -> bool:
    return bool(f["move_vs_base"] and f["move_vs_base"] >= V1["min_move"]
                and f["n_buyers_entry"] >= V1["min_buyers"]
                and f["vol_usd_entry"] >= V1["min_vol_usd"]
                and f["n_snipers"] >= V1["min_snipers"]
                and f["dev_prefix"] not in FACTORIES_BLACKLIST
                and not (f["prior_dev_launches"] >= 2 and f["prior_dev_grads"] == 0))


# ---------- v1.1: v1 + volumen por comprador acotado (contra lavado/operador) ----------
V11 = dict(V1, max_vol_per_buyer=200.0, max_move=20.0)


def rule_v11(f: dict) -> bool:
    vpb = f["vol_usd_entry"] / max(1, f["n_buyers_entry"])
    return rule_v1(f) and vpb <= V11["max_vol_per_buyer"] and (f["move_vs_base"] or 0) <= V11["max_move"]




# ---------- v1.2: v1.1 + confirmación al minuto 3 (congelada 23/10/2026 00:10) ----------
# Las condiciones se miden al minuto 2; la entrada es al minuto 3 y solo si el cierre del
# minuto 3 no cayó más de 10% respecto del cierre del minuto 2 (el operador que vendía, ya vendió).
V12 = dict(V11, entry_min=3, confirm_tol=0.10)


def confirmed(candles: list[dict], created_ts: int, entry_min: int, tol: float, base_min: int = 2) -> bool:
    c2 = entry_candle(candles, created_ts, base_min)
    ck = entry_candle(candles, created_ts, entry_min)
    return bool(c2 and ck and ck["c"] >= c2["c"] * (1 - tol))


# nombre -> (regla sobre features del minuto 2, minuto de entrada, tolerancia de confirmación o None)
RULESETS = {
    "v1":   (rule_v1,  V1["entry_min"],  None),
    "v1.1": (rule_v11, V11["entry_min"], None),
    "v1.2": (rule_v11, V12["entry_min"], V12["confirm_tol"]),
}
