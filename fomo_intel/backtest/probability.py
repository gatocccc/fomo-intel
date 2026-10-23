"""Probabilidad de éxito de una señal de ENTRADA.

Fase 1: tabla de frecuencias con suavizado bayesiano, estratificada por tipo de señal
y por trader, entrenada sobre los eventos históricos (éxito = el token llegó a 2x
dentro de la ventana de holdeo antes de caer 35%). Cuando haya >300 eventos se
reemplaza por un modelo logístico/GBM con más features (liquidez, lead del cluster,
hora del día, variante histórica del trader)."""
from __future__ import annotations

from collections import defaultdict

from ..models import CallEvent


class ProbabilityModel:
    def __init__(self, prior_success: float = 0.35, prior_weight: float = 10.0):
        self.prior = prior_success
        self.k = prior_weight
        self.counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # key -> [éxitos, total]

    @staticmethod
    def _success(ev: CallEvent, tp: float = 2.0, sl: float = 0.35) -> bool:
        return ev.features["peak_multiple"] >= tp and ev.features["ret_24h"] > -sl

    def fit(self, events: list[CallEvent]) -> "ProbabilityModel":
        for ev in events:
            s = int(self._success(ev))
            kind = "ENTRADA_CONFLUENCIA" if ev.features.get("n_clusters", 1) > 1 else "ENTRADA_CLUSTER"
            for key in (f"kind={kind}", f"trader={ev.trader}", f"trader={ev.trader}|variant={ev.variant}"):
                self.counts[key][0] += s
                self.counts[key][1] += 1
        return self

    def _rate(self, key: str) -> float:
        s, n = self.counts.get(key, [0, 0])
        return (s + self.k * self.prior) / (n + self.k)

    def predict(self, feats: dict) -> float:
        kind = feats.get("kind", "ENTRADA_CLUSTER")
        trader = feats.get("trader", "")
        p_kind = self._rate(f"kind={kind}")
        p_trader = self._rate(f"trader={trader}")
        p = 0.5 * p_kind + 0.5 * p_trader
        if feats.get("n_clusters", 1) > 1:
            p = min(0.95, p * 1.25)
        liq = feats.get("liquidity_usd", 0)
        if liq and liq < 100_000:
            p *= 0.85
        return round(p, 3)

    def table(self) -> dict[str, tuple[int, int, float]]:
        return {k: (v[0], v[1], round(self._rate(k), 3)) for k, v in sorted(self.counts.items())}
