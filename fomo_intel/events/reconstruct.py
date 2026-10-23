"""Reconstrucción de 'calls': cada primera compra pública de un trader en un token,
con lo que hizo su cluster antes y después. Clasifica la variante y calcula las
features que después alimentan la probabilidad de éxito."""
from __future__ import annotations

from ..config import EventParams
from ..models import CallEvent, Cluster, Trade
from ..sources.store import Store


def _first_buys(trades: list[Trade]) -> list[Trade]:
    seen, out = set(), []
    for t in trades:
        if t.side == "buy" and t.token not in seen:
            seen.add(t.token)
            out.append(t)
    return out


def _sold_fraction(buys: list[Trade], sells: list[Trade]) -> float:
    bought = sum(t.token_amount for t in buys)
    sold = sum(t.token_amount for t in sells)
    return min(1.0, sold / bought) if bought > 0 else 0.0


def classify(ev: CallEvent, store: Store, ep: EventParams) -> str:
    f = ev.features
    meta = store.token_meta.get(ev.token, {})
    liq = meta.get("liquidity_usd", f.get("liquidity_usd", 0))
    age = ev.ts - meta.get("created_ts", ev.ts - 10 ** 9)
    if ev.cluster_buys_before and f["cluster_sold_4min"] >= 0.5:
        return "frontrun"
    if not ev.cluster_buys_before and (liq < ep.bait_liquidity_usd or age < ep.bait_token_age_s):
        return "baiting"
    if (ev.cluster_buys_before or ev.cluster_buys_after) and f["cluster_sold_3d"] >= 0.5 and f["public_sold_3d"] < 0.25:
        return "holdeo_vidriera"
    if (ev.cluster_buys_before or ev.cluster_buys_after) and f["cluster_sold_3d"] < 0.5:
        return "conviccion"
    return "sin_cluster"


def build_events(store: Store, cluster: Cluster, ep: EventParams, min_score: int = 40) -> list[CallEvent]:
    members = [m.wallet for m in cluster.members if m.score >= min_score]
    pub = cluster.public_wallet
    events = []
    for pb in _first_buys(store.trades_of(pub)):
        tok = store.trades_in_token(pb.token)
        cb_before = [t for t in tok if t.wallet in members and t.side == "buy" and pb.ts - ep.before_window_s <= t.ts < pb.ts]
        cb_after = [t for t in tok if t.wallet in members and t.side == "buy" and pb.ts <= t.ts <= pb.ts + ep.after_window_s]
        cs_after = [t for t in tok if t.wallet in members and t.side == "sell" and pb.ts <= t.ts <= pb.ts + ep.hold_window_s]
        ps_after = [t for t in tok if t.wallet == pub and t.side == "sell" and pb.ts < t.ts <= pb.ts + ep.hold_window_s]
        cluster_buys = cb_before + cb_after + [t for t in tok if t.wallet in members and t.side == "buy" and t.ts < pb.ts - ep.before_window_s]
        cs_4min = [t for t in cs_after if t.ts <= pb.ts + ep.after_window_s]
        pb_price = pb.price_usd or store.price_at(pb.token, pb.ts) or 0.0
        path = store.price_path(pb.token, pb.ts, pb.ts + ep.hold_window_s)
        peak = max((p for _, p in path), default=pb_price)
        p_1h = store.price_at(pb.token, pb.ts + 3600) or pb_price
        p_24h = store.price_at(pb.token, pb.ts + 86400) or pb_price
        features = {
            "cluster_buy_before_usd": sum(t.amount_usd for t in cb_before),
            "cluster_lead_s": (pb.ts - min(t.ts for t in cb_before)) if cb_before else 0,
            "cluster_sold_4min": _sold_fraction(cluster_buys, cs_4min),
            "cluster_sold_3d": _sold_fraction(cluster_buys, cs_after),
            "public_sold_3d": _sold_fraction([pb], ps_after),
            "liquidity_usd": store.token_meta.get(pb.token, {}).get("liquidity_usd", 0),
            "peak_multiple": (peak / pb_price) if pb_price else 1.0,
            "ret_1h": (p_1h / pb_price - 1) if pb_price else 0.0,
            "ret_24h": (p_24h / pb_price - 1) if pb_price else 0.0,
        }
        ev = CallEvent(trader=cluster.trader, token=pb.token, public_tx=pb.tx, ts=pb.ts, public_amount_usd=pb.amount_usd,
                       cluster_buys_before=cb_before, cluster_buys_after=cb_after, cluster_sells_after=cs_after,
                       public_sells_after=ps_after, features=features)
        ev.variant = classify(ev, store, ep)
        events.append(ev)
    return events


def summarize(events: list[CallEvent]) -> dict:
    by = {}
    for e in events:
        d = by.setdefault(e.variant, {"n": 0, "ret_1h": 0.0, "ret_24h": 0.0, "peak": 0.0})
        d["n"] += 1
        d["ret_1h"] += e.features["ret_1h"]
        d["ret_24h"] += e.features["ret_24h"]
        d["peak"] += e.features["peak_multiple"]
    for v in by.values():
        for k in ("ret_1h", "ret_24h", "peak"):
            v[k] = round(v[k] / v["n"], 3)
    return by
