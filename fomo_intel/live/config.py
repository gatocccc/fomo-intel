"""Parámetros de la operación en vivo. Todo lo que puede cambiar sin tocar código vive en
state/control.json (lo lee el bot cada ciclo) o en variables de entorno."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

SOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class LiveParams:
    # --- modo ---
    mode: str = "paper"                 # paper | real
    trading_enabled: bool = True        # False = no abre posiciones nuevas (sigue cerrando las abiertas)
    panic: bool = False                 # True = vende todo y no abre nada
    # --- tamaño y frenos (US$) ---
    size_usd: float = 10.0
    max_open: int = 3
    daily_loss_usd: float = 50.0        # pérdida realizada máxima por día (hora de Buenos Aires)
    total_loss_usd: float = 150.0       # corte de la prueba
    max_trades: int = 30                # corte de la prueba
    max_slippage_pct: float = 8.0       # si la cotización trae más impacto que esto, no compra
    min_sol_reserve: float = 0.02       # SOL que nunca se gasta (fees)
    priority_fee_sol: float = 0.0005
    swap_slippage_pct: float = 10.0     # tolerancia que se le pasa al swap (distinta del guardia de arriba)
    # --- regla de entrada (congelada: v1.2) ---
    eval_min: int = 2
    entry_min: int = 3
    confirm_tol: float = 0.10
    min_move: float = 3.0
    max_move: float = 20.0
    min_buyers: int = 40
    min_vol_usd: float = 2000.0
    max_vol_per_buyer: float = 200.0
    min_snipers: int = 1
    # --- salida ---
    tp_mult: float = 2.0
    tp_frac: float = 0.5
    trail: float = 0.20
    stop: float = 0.30
    max_hold_min: int = 360
    # --- stream (PumpPortal cobra 0,01 SOL por cada 10.000 trades recibidos) ---
    stream_watch_s: float = 150.0       # segundos que se escuchan los trades de cada token nuevo
    stream_sample: float = 1.0          # fracción de tokens nuevos a escuchar (muestreo para investigación)
    # --- simulado ---
    paper_slippage: float = 0.05
    paper_fee: float = 0.01

    @classmethod
    def load(cls, state_dir: Path) -> "LiveParams":
        p = cls()
        f = state_dir / "control.json"
        if f.exists():
            try:
                for k, v in json.load(open(f)).items():
                    if hasattr(p, k):
                        setattr(p, k, v)
            except Exception:  # noqa: BLE001  archivo a medio escribir: se usa el default
                pass
        env_mode = os.getenv("LIVE_MODE")
        if env_mode:
            p.mode = env_mode
        return p

    def save(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        json.dump(asdict(self), open(state_dir / "control.json", "w"), indent=1)


@dataclass
class Env:
    solanatracker_api_key: str = field(default_factory=lambda: os.getenv("SOLANATRACKER_API_KEY", ""))
    helius_api_key: str = field(default_factory=lambda: os.getenv("HELIUS_API_KEY", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("FOMO_DATA_DIR", "data")))
    state_dir: Path = field(default_factory=lambda: Path(os.getenv("FOMO_STATE_DIR", "state")))
    wallet_file: Path = field(default_factory=lambda: Path(os.getenv("FOMO_WALLET_FILE", "secrets/wallet.json")))

    @property
    def rpc_url(self) -> str:
        return os.getenv("SOLANA_RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
