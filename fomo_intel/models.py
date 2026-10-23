"""Modelos de datos normalizados. Todo lo que entra (Helius, Solana Tracker, EVM) se
convierte a estas estructuras; el resto del sistema no sabe de qué cadena vino."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Trade:
    """Un swap de una wallet: compra o venta de `token` contra el activo base."""
    wallet: str
    token: str
    side: Side
    amount_usd: float
    token_amount: float
    ts: int            # unix seconds
    tx: str            # firma / hash, para evidencia
    chain: str = "solana"
    price_usd: float | None = None   # precio implícito del token en el swap


@dataclass(frozen=True)
class Transfer:
    """Transferencia de activo nativo o stable entre dos wallets (no swap)."""
    src: str
    dst: str
    amount_usd: float
    ts: int
    tx: str
    chain: str = "solana"
    asset: str = "SOL"


@dataclass
class WalletLabel:
    wallet: str
    kind: str          # exchange_deposit | exchange_hot | kol | bot | platform | unknown
    name: str = ""


@dataclass
class Evidence:
    signal: str        # nombre de la señal (ver graph/scoring.py)
    weight: int
    detail: str
    txs: list[str] = field(default_factory=list)


@dataclass
class ClusterMember:
    wallet: str
    score: int
    evidence: list[Evidence]

    @property
    def confidence(self) -> str:
        if self.score >= 70:
            return "confirmado"
        if self.score >= 40:
            return "probable"
        return "descartado"


@dataclass
class Cluster:
    trader: str                 # handle FOMO
    public_wallet: str
    members: list[ClusterMember]

    def confirmed(self) -> list[str]:
        return [m.wallet for m in self.members if m.score >= 70]

    def probable(self) -> list[str]:
        return [m.wallet for m in self.members if 40 <= m.score < 70]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CallEvent:
    """Una compra pública de un trader en un token = un 'call'. Alrededor se mide
    qué hizo su cluster antes y después."""
    trader: str
    token: str
    public_tx: str
    ts: int
    public_amount_usd: float
    cluster_buys_before: list[Trade]
    cluster_buys_after: list[Trade]
    cluster_sells_after: list[Trade]
    public_sells_after: list[Trade]
    variant: str = "sin_clasificar"   # frontrun | holdeo_vidriera | baiting | conviccion
    features: dict = field(default_factory=dict)


@dataclass
class Signal:
    kind: str          # ENTRADA_CLUSTER | ENTRADA_CONFLUENCIA | CONFIRMACION | SALIDA_DISTRIBUCION | SALIDA_DEFENSIVA | IGNORAR_BAITING
    token: str
    ts: int
    trader: str
    probability: float   # probabilidad estimada de éxito (0-1) para las ENTRADA
    size_multiplier: float = 1.0
    evidence_txs: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class BacktestTrade:
    token: str
    trader: str
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    size_usd: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    signal_kind: str
    probability: float
