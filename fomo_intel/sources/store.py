"""Almacén local en JSON (fase 1). Todo lo descargado se guarda acá para que el
clustering y el backtest corran offline y sean reproducibles. En fase 2 se
reemplaza por PostgreSQL/TimescaleDB con la misma interfaz."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from ..models import Trade, Transfer, WalletLabel


class Store:
    def __init__(self, data_dir: str):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.trades: list[Trade] = []
        self.transfers: list[Transfer] = []
        self.labels: dict[str, WalletLabel] = {}
        self.prices: dict[str, list[tuple[int, float]]] = {}   # token -> [(ts, price_usd)]
        self.token_meta: dict[str, dict] = {}                  # token -> {liquidity_usd, created_ts}
        self._load()

    # ---------- persistencia ----------
    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def _load(self) -> None:
        if self._path("trades").exists():
            self.trades = [Trade(**t) for t in json.loads(self._path("trades").read_text())]
        if self._path("transfers").exists():
            self.transfers = [Transfer(**t) for t in json.loads(self._path("transfers").read_text())]
        if self._path("labels").exists():
            self.labels = {k: WalletLabel(**v) for k, v in json.loads(self._path("labels").read_text()).items()}
        if self._path("prices").exists():
            self.prices = {k: [tuple(p) for p in v] for k, v in json.loads(self._path("prices").read_text()).items()}
        if self._path("token_meta").exists():
            self.token_meta = json.loads(self._path("token_meta").read_text())

    def save(self) -> None:
        self._path("trades").write_text(json.dumps([asdict(t) for t in self.trades]))
        self._path("transfers").write_text(json.dumps([asdict(t) for t in self.transfers]))
        self._path("labels").write_text(json.dumps({k: asdict(v) for k, v in self.labels.items()}))
        self._path("prices").write_text(json.dumps(self.prices))
        self._path("token_meta").write_text(json.dumps(self.token_meta))

    # ---------- escritura sin duplicados ----------
    def add_trades(self, trades: list[Trade]) -> int:
        seen = {(t.tx, t.wallet, t.token, t.side) for t in self.trades}
        new = [t for t in trades if (t.tx, t.wallet, t.token, t.side) not in seen]
        self.trades.extend(new)
        return len(new)

    def add_transfers(self, transfers: list[Transfer]) -> int:
        seen = {(t.tx, t.src, t.dst) for t in self.transfers}
        new = [t for t in transfers if (t.tx, t.src, t.dst) not in seen]
        self.transfers.extend(new)
        return len(new)

    # ---------- consultas ----------
    def trades_of(self, wallet: str) -> list[Trade]:
        return sorted((t for t in self.trades if t.wallet == wallet), key=lambda t: t.ts)

    def trades_in_token(self, token: str) -> list[Trade]:
        return sorted((t for t in self.trades if t.token == token), key=lambda t: t.ts)

    def transfers_from(self, wallet: str) -> list[Transfer]:
        return [t for t in self.transfers if t.src == wallet]

    def transfers_to(self, wallet: str) -> list[Transfer]:
        return [t for t in self.transfers if t.dst == wallet]

    def first_funder(self, wallet: str) -> Transfer | None:
        inc = sorted(self.transfers_to(wallet), key=lambda t: t.ts)
        return inc[0] if inc else None

    def is_exchange(self, wallet: str) -> bool:
        lab = self.labels.get(wallet)
        return bool(lab and lab.kind.startswith("exchange"))

    def price_at(self, token: str, ts: int) -> float | None:
        """Último precio conocido en o antes de ts. Si no hay serie, usa el precio
        implícito del último trade."""
        series = self.prices.get(token)
        if series:
            best = None
            for pts, p in series:
                if pts <= ts:
                    best = p
                else:
                    break
            if best is not None:
                return best
        last = None
        for t in self.trades_in_token(token):
            if t.ts <= ts and t.price_usd:
                last = t.price_usd
            elif t.ts > ts:
                break
        return last

    def price_path(self, token: str, start_ts: int, end_ts: int) -> list[tuple[int, float]]:
        series = self.prices.get(token)
        if series:
            return [(ts, p) for ts, p in series if start_ts <= ts <= end_ts]
        return [(t.ts, t.price_usd) for t in self.trades_in_token(token)
                if start_ts <= t.ts <= end_ts and t.price_usd]
