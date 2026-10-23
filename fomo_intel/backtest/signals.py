"""Motor de señales: recorre los trades de los clusters en orden cronológico y emite
Signal. Es el mismo código que en fase 2 corre sobre el stream en tiempo real; en el
backtest se alimenta con el historial."""
from __future__ import annotations

from collections import defaultdict

from ..config import EventParams
from ..models import Cluster, Signal, Trade
from ..sources.store import Store
from .probability import ProbabilityModel


def generate_signals(store: Store, clusters: list[Cluster], ep: EventParams, prob: ProbabilityModel,
                     confluence_window_s: int = 600, distribution_frac: float = 0.25) -> list[Signal]:
    member_of: dict[str, str] = {}
    public_of: dict[str, str] = {}
    for c in clusters:
        public_of[c.public_wallet] = c.trader
        for w in c.confirmed():
            member_of[w] = c.trader

    watched = set(member_of) | set(public_of)
    stream = sorted((t for t in store.trades if t.wallet in watched), key=lambda t: t.ts)

    signals: list[Signal] = []
    position: dict[tuple[str, str], float] = defaultdict(float)          # (wallet, token) -> qty
    entered: dict[tuple[str, str], int] = {}                            # (trader, token) -> ts de ENTRADA
    public_bought: set[tuple[str, str]] = set()
    recent_cluster_buys: dict[str, list[tuple[int, str]]] = defaultdict(list)  # token -> [(ts, trader)]

    for t in stream:
        key = (t.wallet, t.token)
        trader = member_of.get(t.wallet) or public_of.get(t.wallet)
        is_member = t.wallet in member_of
        meta = store.token_meta.get(t.token, {})
        liq = meta.get("liquidity_usd", 0)

        if t.side == "buy":
            position[key] += t.token_amount
            if is_member:
                recent_cluster_buys[t.token].append((t.ts, trader))
                others = {tr for ts, tr in recent_cluster_buys[t.token] if t.ts - ts <= confluence_window_s and tr != trader}
                if (trader, t.token) not in entered and liq >= ep.min_liquidity_usd:
                    kind = "ENTRADA_CONFLUENCIA" if others else "ENTRADA_CLUSTER"
                    feats = {"kind": kind, "trader": trader, "liquidity_usd": liq, "n_clusters": 1 + len(others)}
                    signals.append(Signal(kind=kind, token=t.token, ts=t.ts, trader=trader,
                                          probability=prob.predict(feats), size_multiplier=2.0 if others else 1.0,
                                          evidence_txs=[t.tx], note=f"cluster de @{trader} compró US${t.amount_usd:,.0f}"))
                    entered[(trader, t.token)] = t.ts
            else:  # compra pública
                public_bought.add((trader, t.token))
                if (trader, t.token) in entered:
                    signals.append(Signal(kind="CONFIRMACION", token=t.token, ts=t.ts, trader=trader, probability=0.0,
                                          evidence_txs=[t.tx], note="call público con cluster adentro"))
                else:
                    age = t.ts - meta.get("created_ts", 0)
                    if liq < ep.bait_liquidity_usd or age < ep.bait_token_age_s:
                        signals.append(Signal(kind="IGNORAR_BAITING", token=t.token, ts=t.ts, trader=trader, probability=0.0,
                                              evidence_txs=[t.tx], note="compra pública sin cluster en token ilíquido/nuevo"))
        else:  # venta
            held = position.get(key, 0.0)
            if is_member and held > 0 and (trader, t.token) in entered:
                frac = t.token_amount / held
                if frac >= distribution_frac:
                    signals.append(Signal(kind="SALIDA_DISTRIBUCION", token=t.token, ts=t.ts, trader=trader, probability=0.0,
                                          evidence_txs=[t.tx], note=f"side wallet vendió {frac:.0%} de su posición"))
            position[key] = max(0.0, held - t.token_amount)
    return signals
