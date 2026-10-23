"""Puntaje de vinculación entre la wallet pública y cada candidata.

Cada señal produce Evidence con las transacciones que la prueban. El puntaje es la
suma de pesos (tope 100). Umbrales: >=70 confirmado, 40-69 probable.
"""
from __future__ import annotations

from ..config import ClusterParams
from ..models import Cluster, ClusterMember, Evidence
from ..sources.store import Store


def _funding(store: Store, public: str, cand: str, cluster_so_far: set[str], w: int) -> Evidence | None:
    first = store.first_funder(cand)
    if first and (first.src == public or first.src in cluster_so_far):
        who = "wallet pública" if first.src == public else f"wallet del cluster {first.src[:6]}"
        return Evidence("fondeo_directo", w, f"primer ingreso desde {who} (US${first.amount_usd:,.0f})", [first.tx])
    return None


def _cex_deposit(store: Store, public: str, cand: str, w: int) -> Evidence | None:
    pub_dep = {t.dst: t.tx for t in store.transfers_from(public) if store.is_exchange(t.dst)}
    for t in store.transfers_from(cand):
        if t.dst in pub_dep:
            name = store.labels[t.dst].name or t.dst[:8]
            return Evidence("misma_direccion_deposito_cex", w, f"ambas depositan en {name}", [pub_dep[t.dst], t.tx])
    return None


def _circular(store: Store, public: str, cand: str, cluster_so_far: set[str], w: int) -> Evidence | None:
    targets = {public} | cluster_so_far
    back = [t for t in store.transfers_from(cand) if t.dst in targets]
    if back:
        total = sum(t.amount_usd for t in back)
        return Evidence("flujo_circular", w, f"US${total:,.0f} devueltos a la pública/cluster en {len(back)} transferencias",
                        [t.tx for t in back[:5]])
    return None


def _cooccurrence(store: Store, public: str, cand: str, w: int, min_tokens: int) -> Evidence | None:
    pub_tokens = {t.token for t in store.trades_of(public) if t.side == "buy"}
    cand_tokens = {t.token for t in store.trades_of(cand) if t.side == "buy"}
    common = pub_tokens & cand_tokens
    if len(common) >= min_tokens:
        txs = [t.tx for t in store.trades_of(cand) if t.token in common and t.side == "buy"][:5]
        return Evidence("coocurrencia_tokens", w, f"{len(common)} tokens comprados por ambas (pública tiene {len(pub_tokens)})", txs)
    return None


def _timing(store: Store, public: str, cand: str, cp: ClusterParams) -> Evidence | None:
    """Candidata compra en [-before, +after] respecto de cada compra pública. Un bot
    copiador compra SIEMPRE después; una side wallet compra antes o casi a la vez."""
    pub_buys = [t for t in store.trades_of(public) if t.side == "buy"]
    if not pub_buys:
        return None
    cand_buys = store.trades_of(cand)
    hits, before_hits, txs = 0, 0, []
    for pb in pub_buys:
        for cb in cand_buys:
            if cb.token == pb.token and cb.side == "buy" and pb.ts - cp.timing_before_s <= cb.ts <= pb.ts + cp.timing_after_s:
                hits += 1
                before_hits += cb.ts <= pb.ts
                txs.append(cb.tx)
                break
    ratio = hits / len(pub_buys)
    if hits >= 2 and ratio >= cp.timing_min_ratio and before_hits / hits >= 0.5:
        return Evidence("sincronia_temporal", cp.timing_weight,
                        f"compra en ventana en {hits}/{len(pub_buys)} calls ({before_hits} antes de la pública)", txs[:5])
    return None


def score_cluster(store: Store, trader: str, public_wallet: str, candidates: list[str], cp: ClusterParams) -> Cluster:
    members: list[ClusterMember] = []
    confirmed: set[str] = set()
    # dos pasadas: la segunda deja que el fondeo/flujo desde miembros ya confirmados cuente
    for _pass in range(2):
        members, confirmed_next = [], set()
        for cand in candidates:
            ev = [e for e in (
                _funding(store, public_wallet, cand, confirmed, cp.funding_weight),
                _cex_deposit(store, public_wallet, cand, cp.cex_deposit_weight),
                _circular(store, public_wallet, cand, confirmed, cp.circular_flow_weight),
                _cooccurrence(store, public_wallet, cand, cp.cooccurrence_weight, cp.cooccurrence_min_tokens),
                _timing(store, public_wallet, cand, cp),
            ) if e]
            score = min(100, sum(e.weight for e in ev))
            if score >= cp.probable_threshold:
                members.append(ClusterMember(cand, score, ev))
            if score >= cp.confirmed_threshold:
                confirmed_next.add(cand)
        confirmed = confirmed_next
    members.sort(key=lambda m: -m.score)
    return Cluster(trader=trader, public_wallet=public_wallet, members=members)
