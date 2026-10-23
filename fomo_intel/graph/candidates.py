"""Búsqueda de wallets candidatas a side wallet, partiendo de la wallet pública.

Tres caminos, hasta `hops` saltos:
  1. transferencias salientes de SOL/stables a wallets no etiquetadas como exchange
  2. wallets que compraron el mismo token en la ventana alrededor de cada compra pública
  3. wallets que comparten dirección de depósito en exchange
"""
from __future__ import annotations

from collections import Counter

from ..config import ClusterParams, EventParams
from ..sources.store import Store


def find_candidates(store: Store, public_wallet: str, cp: ClusterParams, ep: EventParams,
                    max_candidates: int = 200) -> list[str]:
    frontier, seen, scores = {public_wallet}, {public_wallet}, Counter()

    for hop in range(cp.hops):
        next_frontier = set()
        for w in frontier:
            # 1) a quién le mandó plata
            for tr in store.transfers_from(w):
                if tr.dst not in seen and not store.is_exchange(tr.dst):
                    scores[tr.dst] += 3 if hop == 0 else 1
                    next_frontier.add(tr.dst)
            # 3) con quién comparte depósito de exchange
            for tr in store.transfers_from(w):
                if store.is_exchange(tr.dst):
                    for other in store.transfers_to(tr.dst):
                        if other.src not in seen and other.src != w:
                            scores[other.src] += 4
                            next_frontier.add(other.src)
        # 2) co-compradores en ventana (solo desde la wallet pública)
        if hop == 0:
            for t in store.trades_of(public_wallet):
                if t.side != "buy":
                    continue
                for other in store.trades_in_token(t.token):
                    if (other.wallet != public_wallet and other.side == "buy"
                            and t.ts - ep.before_window_s <= other.ts <= t.ts + cp.timing_after_s):
                        scores[other.wallet] += 1
                        next_frontier.add(other.wallet)
        seen |= next_frontier
        frontier = next_frontier

    seen.discard(public_wallet)
    ranked = [w for w, _ in scores.most_common() if w in seen and not store.is_exchange(w)]
    return ranked[:max_candidates]
