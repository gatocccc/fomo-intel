"""Configuración por variables de entorno (ver .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Carga .env del directorio del proyecto si existe (no pisa variables ya definidas)."""
    for cand in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break


_load_dotenv()


@dataclass
class ClusterParams:
    hops: int = 2
    funding_weight: int = 35
    cex_deposit_weight: int = 40
    circular_flow_weight: int = 25
    cooccurrence_weight: int = 20
    timing_weight: int = 25
    fee_payer_weight: int = 40
    cooccurrence_min_tokens: int = 3
    timing_before_s: int = 120
    timing_after_s: int = 30
    timing_min_ratio: float = 0.6
    confirmed_threshold: int = 70
    probable_threshold: int = 40


@dataclass
class EventParams:
    before_window_s: int = 300      # cuánto antes del call se mira al cluster
    after_window_s: int = 420       # ventana de distribución típica (Anglio: ~4 min; margen a 7)
    hold_window_s: int = 3 * 86400  # para "holdeo de vidriera"
    min_liquidity_usd: float = 50_000
    bait_liquidity_usd: float = 30_000
    bait_token_age_s: int = 600


@dataclass
class TradingParams:
    size_usd: float = 200.0
    max_pct_per_trade: float = 0.02
    max_pct_per_token: float = 0.10
    tp_levels: tuple = ((2.0, 0.5), (4.0, 0.3))   # (múltiplo, fracción a vender)
    trailing_stop_pct: float = 0.25
    confirm_sell_frac: float = 0.4     # fracción vendida al call público (CONFIRMACION)
    stop_loss_pct: float = 0.35
    max_hold_s: int = 6 * 3600
    latency_s: float = 1.5            # Solana; 3.0 en Robinhood Chain
    slippage_pct_high_liq: float = 0.03
    slippage_pct_low_liq: float = 0.08
    fee_pct: float = 0.01             # fee+tip estimado por lado
    daily_loss_kill_pct: float = 0.05


@dataclass
class Settings:
    helius_api_key: str = field(default_factory=lambda: os.getenv("HELIUS_API_KEY", ""))
    solanatracker_api_key: str = field(default_factory=lambda: os.getenv("SOLANATRACKER_API_KEY", ""))
    data_dir: str = field(default_factory=lambda: os.getenv("FOMO_DATA_DIR", "data"))
    cluster: ClusterParams = field(default_factory=ClusterParams)
    events: EventParams = field(default_factory=EventParams)
    trading: TradingParams = field(default_factory=TradingParams)


# Wallets FOMO verificadas al 30-09-2026 (Fomo Wallet Finder). Punto de partida de fase 1.
SEED_TRADERS: dict[str, dict[str, str]] = {
    "unipcs": {"solana": "2heJbC32Tpfcb3nbUb5ER61K11FGZVfVGtVnDm6LDogF", "evm": "0x0a6ebed0155edb4b21d92ad02897a626cd90119e"},
    "pointfarmcap": {"solana": "Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit", "evm": "0xfd87eda88be6c372453b721da63d58ad1a5b2d94"},
    "The__Solstice": {"solana": "4ugDhHJ8XDXAeABmrNmGffFaLbJb9BkPyiFGVSV9ocwo", "evm": "0xd1c77a04b87393e98a1220532e72e8f7d0a31c5a"},
    "Salem1299534": {"solana": "2yXwy5Dsa1XtEXcsrkFVRJeyuWD3qKkMN3pP3p5VTW3V", "evm": "0xb8f305f27ccc406373de0082cc06cb1d065504ea"},
    "AvgJoesCrypto": {"solana": "H2QSGECp13sFLJgdTsDtayX3dk18Dm6sQMSQKcew7Xzk", "evm": "0x06de9c48b1e639ed5c13ec8fbd4080a38e39f2d1"},
    "frankdegods": {"solana": "498g1rVnFcnjBjpfw1xyqA1WvgQXUU8RWuELjxkjAayQ", "evm": ""},
    "change": {"solana": "J9WiAZKf8JnCkHFL8fLCCXdEgdoLjLRqU2EGsDjdqYga", "evm": ""},
}
