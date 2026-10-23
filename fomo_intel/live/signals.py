"""Regla v1.2 medida en vivo con el stream (mismas definiciones que el backtest sobre velas de 1 min).

En el backtest, "minuto 2" es la primera vela de reloj que empieza a >= 120 s de la creación y
se usa su CIERRE (es decir, el precio ~60 s después de que empieza esa vela). Acá se replica
exactamente eso con tiempos de reloj:
  T2 = fin de la vela que empieza en el primer múltiplo de 60 s >= created+120
  T3 = fin de la vela que empieza en el primer múltiplo de 60 s >= created+180  (entrada)
Condiciones (al T2): move = precio(T2)/base >= 3 y <= 20; compradores únicos en los primeros
120 s >= 40; volumen de las velas que empiezan <= created+120 >= US$2000; US$/comprador <= 200;
snipers >= 1; dev no fábrica. Confirmación (al T3): precio(T3) >= 0.9 * precio(T2).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass

import requests

from ..backtest.rules import FACTORIES_BLACKLIST
from .config import LiveParams
from .stream import TokenState

log = logging.getLogger("live.signals")
ST_BASE = "https://data.solanatracker.io"


def candle_start(ts: float) -> int:
    return int(math.ceil(ts / 60.0) * 60)


def t2_of(created_ts: float, eval_min: int) -> int:
    return candle_start(created_ts + eval_min * 60) + 60


def t3_of(created_ts: float, entry_min: int) -> int:
    return candle_start(created_ts + entry_min * 60) + 60


@dataclass
class Features:
    mint: str
    symbol: str
    created_ts: float
    t2: int
    t3: int
    base_price: float
    px_t2: float
    move: float
    n_buyers_60s: int
    n_buyers_120s: int
    vol_sol: float
    vol_usd: float
    vol_per_buyer: float
    n_snipers_proxy: int
    n_snipers_st: int | None
    creator: str
    creator_prior_24h: int
    rugged_st: bool
    risk_st: dict
    early_buyers: list      # [[wallet, sol_comprado, segundos_desde_creacion], ...] compradores de los primeros 120 s (para reputación de billeteras)
    passes_proxy: bool
    passes: bool
    reasons: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def _early_buyers(st: TokenState, t0: float, limit_s: float = 120.0) -> list:
    agg: dict[str, list] = {}
    for t in st.trades:
        if t.side == "buy" and t.ts - t0 <= limit_s:
            a = agg.setdefault(t.wallet, [t.wallet, 0.0, round(t.ts - t0, 1)])
            a[1] = round(a[1] + t.sol, 4)
    return sorted(agg.values(), key=lambda x: x[2])[:150]


def features_at_t2(st: TokenState, p: LiveParams, sol_usd: float, creator_prior_24h: int) -> Features:
    t0 = st.created_ts
    t2, t3 = t2_of(t0, p.eval_min), t3_of(t0, p.entry_min)
    px2 = st.price_at(t2)
    move = px2 / st.base_price if st.base_price > 0 else 0.0
    buys120 = {t.wallet for t in st.trades if t.side == "buy" and t.ts <= t0 + 120}
    buys60 = {t.wallet for t in st.trades if t.side == "buy" and t.ts <= t0 + 60}
    vol_cut = candle_start(t0 + p.eval_min * 60) + 60       # velas que EMPIEZAN <= created+120
    vol_sol = sum(t.sol for t in st.trades if t.ts < vol_cut)
    vol_usd = vol_sol * sol_usd
    nb = len(buys120)
    vpb = vol_usd / max(1, nb)
    snipers_proxy = len({t.wallet for t in st.trades if t.side == "buy" and t.wallet != st.creator and t.ts - t0 <= 1.5})
    reasons = []
    if move < p.min_move: reasons.append(f"move {move:.1f}x < {p.min_move}")
    if move > p.max_move: reasons.append(f"move {move:.1f}x > {p.max_move}")
    if nb < p.min_buyers: reasons.append(f"compradores {nb} < {p.min_buyers}")
    if nb < len(buys60): reasons.append("compradores no crecen")
    if vol_usd < p.min_vol_usd: reasons.append(f"vol ${vol_usd:,.0f} < {p.min_vol_usd:,.0f}")
    if vpb > p.max_vol_per_buyer: reasons.append(f"${vpb:.0f}/comprador > {p.max_vol_per_buyer}")
    if st.creator[:6] in FACTORIES_BLACKLIST: reasons.append("dev fábrica")
    if creator_prior_24h >= 2: reasons.append(f"dev lanzó {creator_prior_24h} tokens en 24h")
    return Features(mint=st.mint, symbol=st.symbol, created_ts=t0, t2=t2, t3=t3, base_price=st.base_price, px_t2=px2,
                    move=round(move, 2), n_buyers_60s=len(buys60), n_buyers_120s=nb, vol_sol=round(vol_sol, 3),
                    vol_usd=round(vol_usd, 0), vol_per_buyer=round(vpb, 1), n_snipers_proxy=snipers_proxy,
                    n_snipers_st=None, creator=st.creator, creator_prior_24h=creator_prior_24h, rugged_st=False, risk_st={},
                    early_buyers=_early_buyers(st, t0),
                    passes_proxy=not reasons, passes=False, reasons=reasons)


class STClient:
    """Solo lo mínimo que la operación en vivo pide a Solana Tracker (cuenta requests)."""

    def __init__(self, api_key: str):
        self.h = {"x-api-key": api_key}
        self.requests_made = 0
        self._sol = (0.0, 0.0)   # (precio, ts)

    def _get(self, path: str, **params):
        self.requests_made += 1
        r = requests.get(f"{ST_BASE}{path}", headers=self.h, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def sol_usd(self, max_age: float = 300.0) -> float:
        px, ts = self._sol
        if time.time() - ts < max_age and px > 0:
            return px
        try:
            d = self._get("/price", token="So11111111111111111111111111111111111111112")
            px = float(d.get("price") or 0)
            if px > 0:
                self._sol = (px, time.time())
        except Exception as e:  # noqa: BLE001
            log.warning("precio SOL: %s", e)
        return self._sol[0] or px

    def token_risk(self, mint: str) -> dict:
        """snipers, rugged, launchpad. 1 request."""
        d = self._get(f"/tokens/{mint}")
        risk = d.get("risk") or {}
        pools = d.get("pools") or [{}]
        curve = min(pools, key=lambda x: x.get("createdAt") or 9e18)
        def pct(k): return float((risk.get(k) or {}).get("totalPercentage") or 0)
        return {"n_snipers": int((risk.get("snipers") or {}).get("count") or len((risk.get("snipers") or {}).get("wallets") or [])),
                "rugged": bool(risk.get("rugged")), "launchpad": (curve.get("market") or "").replace("-curve", ""),
                "score": int(risk.get("score") or 0),
                "risk": {"score": int(risk.get("score") or 0), "top10": float(risk.get("top10") or 0),
                         "dev_pct": float((risk.get("dev") or {}).get("percentage") or 0),
                         "snipers_pct": pct("snipers"), "insiders_pct": pct("insiders"), "bundlers_pct": pct("bundlers"),
                         "n_insiders": int((risk.get("insiders") or {}).get("count") or 0), "n_bundlers": int((risk.get("bundlers") or {}).get("count") or 0),
                         "risks": [r.get("name") if isinstance(r, dict) else str(r) for r in (risk.get("risks") or [])][:8],
                         "holders": int(d.get("holders") or 0), "mcap_usd": float(((curve.get("marketCap") or {}).get("usd")) or 0),
                         "liq_usd": float(((curve.get("liquidity") or {}).get("usd")) or 0)}}

    def price(self, mint: str) -> float | None:
        try:
            d = self._get("/price", token=mint)
            return float(d.get("price") or 0) or None
        except Exception:  # noqa: BLE001
            return None


def enrich(f: Features, p: LiveParams, st_client: STClient) -> Features:
    """Completa con Solana Tracker lo que el stream no sabe (snipers) y decide."""
    try:
        r = st_client.token_risk(f.mint)
        f.n_snipers_st, f.rugged_st, f.risk_st = r["n_snipers"], r["rugged"], r.get("risk", {})
    except Exception as e:  # noqa: BLE001
        log.warning("%s: sin datos de riesgo (%s); uso proxy", f.symbol, e)
    n_sn = f.n_snipers_st if f.n_snipers_st is not None else f.n_snipers_proxy
    if n_sn < p.min_snipers:
        f.reasons.append(f"snipers {n_sn} < {p.min_snipers}")
    if f.rugged_st:
        f.reasons.append("marcado rugged")
    f.passes = not f.reasons
    return f


def confirmed(st: TokenState, f: Features, p: LiveParams) -> tuple[bool, float]:
    px3 = st.price_at(f.t3)
    return (px3 >= f.px_t2 * (1 - p.confirm_tol)), px3
