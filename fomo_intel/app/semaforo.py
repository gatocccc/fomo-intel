"""Semáforo de chances: simula miles de caminos posibles para un objetivo y un plazo.

Cada plan tiene una distribución de resultados por operación. Mientras haya pocas operaciones reales,
se usa una distribución inicial (supuestos declarados, PLANS) mezclada con los resultados reales que haya;
a medida que se acumulan operaciones reales, pesan cada vez más. La respuesta siempre dice con cuántas
operaciones reales se calculó.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

STATE = Path("state")

# Supuestos iniciales por plan (se reemplazan con datos reales a medida que el plan opera).
#   win: probabilidad de ganar una operación · up/down: resultado promedio al ganar / perder
#   spread: dispersión relativa del resultado · frac: parte del capital por operación · per_day: operaciones por día
PLANS = {
    "agresivo": {"nombre": "Agresivo", "mercados": "Memecoins chicas (US$300K–3M)",
                 "win": 0.42, "up": 0.55, "down": -0.30, "spread": 0.8, "frac": 0.33, "per_day": 1.5,
                 "fuente": "desk"},
    "equilibrado": {"nombre": "Equilibrado", "mercados": "Memecoins medianas y grandes (US$3M–500M)",
                    "win": 0.45, "up": 0.20, "down": -0.13, "spread": 0.6, "frac": 0.30, "per_day": 1.2,
                    "fuente": "plan_equilibrado"},
    "tradicional": {"nombre": "Tradicional", "mercados": "SOL, BTC, ETH y JUP",
                    "win": 0.50, "up": 0.07, "down": -0.04, "spread": 0.5, "frac": 0.50, "per_day": 0.4,
                    "fuente": "plan_tradicional"},
}
MIN_REAL = 30  # operaciones reales para dejar de llamarlo "preliminar"


def _real_returns(fuente: str) -> list[float]:
    f = STATE / ("desk" if fuente == "desk" else fuente) / "closed.jsonl"
    out = []
    if f.exists():
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line).get("ret")
                if r is not None:
                    out.append(float(r))
            except Exception:  # noqa: BLE001
                pass
    return out


def _sample(p: dict, real: list[float], rng: random.Random) -> float:
    # Mezcla: con n operaciones reales, la probabilidad de usar una real es n / (n + MIN_REAL).
    if real and rng.random() < len(real) / (len(real) + MIN_REAL):
        return rng.choice(real)
    base = p["up"] if rng.random() < p["win"] else p["down"]
    r = base * (1 + rng.gauss(0, p["spread"]))
    if base > 0:
        return max(r, 0.0)
    return max(min(r, 0.0), -0.95)


def simulate(plan: str, objetivo: float, dias: int, paths: int = 4000, seed: int = 7) -> dict:
    p = PLANS[plan]
    real = _real_returns(p["fuente"])
    rng = random.Random(seed)
    hits = halves = 0
    finals = []
    n_trades = max(1, round(p["per_day"] * dias))
    for _ in range(paths):
        eq = 1.0
        hit = False
        for _ in range(n_trades):
            eq *= 1 + p["frac"] * _sample(p, real, rng)
            if eq >= objetivo:
                hit = True
            if eq <= 0.5:
                break
        hits += hit
        halves += eq <= 0.5
        finals.append(eq)
    finals.sort()
    prob = hits / paths
    half = halves / paths
    nivel = 2 if prob >= 0.60 else 1 if prob >= 0.25 else 0
    # el riesgo de perder la mitad baja el color: una meta probable con mucho riesgo no es verde
    nivel -= (1 if half >= 0.25 else 0) + (1 if half >= 0.50 else 0)
    color = ("rojo", "amarillo", "verde")[max(nivel, 0)]
    return {"plan": plan, "nombre": p["nombre"], "mercados": p["mercados"],
            "prob_objetivo": round(prob, 3), "prob_perder_mitad": round(half, 3),
            "mediana": round(finals[len(finals) // 2], 3), "color": color,
            "ops_reales": len(real), "preliminar": len(real) < MIN_REAL}


def sugerido(plan: str, dias: int) -> float | None:
    """Objetivo más alto que todavía da amarillo o verde con ese plan y plazo."""
    best = None
    for k in range(101, 400, 2):
        obj = k / 100
        if simulate(plan, obj, dias, paths=1200)["color"] != "rojo":
            best = obj
        else:
            break
    return best


def semaforo(objetivo: float, dias: int) -> dict:
    dias = max(7, min(int(dias), 120))
    objetivo = round(max(1.01, min(float(objetivo), 100.0)), 2)
    key = (objetivo, dias, tuple(len(_real_returns(p["fuente"])) for p in PLANS.values()))
    if key in _CACHE:
        return _CACHE[key]
    planes = []
    for k in PLANS:
        r = simulate(k, objetivo, dias)
        if r["color"] == "rojo":
            r["objetivo_sugerido"] = sugerido(k, dias)
        planes.append(r)
    out = {"objetivo": objetivo, "dias": dias, "planes": planes}
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[key] = out
    return out


_CACHE: dict = {}


if __name__ == "__main__":
    print(json.dumps(semaforo(2.0, 30), indent=1, ensure_ascii=False))
