"""Posiciones, frenos de riesgo y registro.

Archivos en state/:
  positions.json   posiciones abiertas (se reescribe en cada cambio)
  trades.jsonl     una línea por fill (compra o venta), con precio esperado vs real
  closed.jsonl     una línea por posición cerrada (resultado neto)
  signals.jsonl    cada token que llegó a evaluarse al minuto 2 (pase o no), para auditar
  live_summary.json  resumen para el dashboard
  STOP             si existe, no se abren posiciones nuevas (frenos automáticos lo crean)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import LiveParams
from .executor import Fill

log = logging.getLogger("live.portfolio")
BA = timezone(timedelta(hours=-3))


def ba_day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), BA).strftime("%Y-%m-%d")


@dataclass
class Position:
    mint: str
    symbol: str
    opened_ts: float
    entry_price: float          # SOL/token efectivo
    tokens: float               # tokens que quedan
    tokens_initial: float
    sol_in: float               # SOL gastados
    sol_out: float = 0.0        # SOL recibidos hasta ahora
    peak_price: float = 0.0
    tp_done: bool = False
    sol_usd_at_open: float = 0.0
    exits: list = field(default_factory=list)   # [{ts, why, tokens, sol, price}]
    last_price: float = 0.0
    last_ts: float = 0.0
    pending_sell: bool = False

    @property
    def size_usd(self) -> float:
        return self.sol_in * self.sol_usd_at_open

    def mult(self, px: float) -> float:
        return px / self.entry_price if self.entry_price > 0 else 0.0


class Portfolio:
    def __init__(self, state_dir: Path, p: LiveParams):
        self.dir = Path(state_dir); self.dir.mkdir(parents=True, exist_ok=True)
        self.p = p
        self.positions: dict[str, Position] = {}
        self._load()

    # ---------- persistencia ----------
    def _load(self) -> None:
        f = self.dir / "positions.json"
        if f.exists():
            for d in json.load(open(f)).values():
                self.positions[d["mint"]] = Position(**d)

    def save(self) -> None:
        tmp = self.dir / "positions.json.tmp"
        json.dump({m: asdict(x) for m, x in self.positions.items()}, open(tmp, "w"), indent=1)
        tmp.replace(self.dir / "positions.json")

    def _append(self, name: str, row: dict) -> None:
        with open(self.dir / name, "a") as f:
            f.write(json.dumps(row) + "\n")

    def _read(self, name: str) -> list[dict]:
        f = self.dir / name
        if not f.exists():
            return []
        out = []
        for line in open(f):
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except json.JSONDecodeError: pass
        return out

    # ---------- registro ----------
    def log_signal(self, feats: dict, decision: str) -> None:
        self._append("signals.jsonl", {"ts": time.time(), "decision": decision, **feats})

    def log_fill(self, f: Fill, mode: str, why: str, sol_usd: float) -> None:
        self._append("trades.jsonl", {"ts": time.time(), "mode": mode, "why": why, "sol_usd": sol_usd, **asdict(f)})

    # ---------- frenos ----------
    def closed(self) -> list[dict]:
        return self._read("closed.jsonl")

    def realized_usd(self, day: str | None = None) -> float:
        rows = self.closed()
        if day:
            rows = [r for r in rows if r.get("day") == day]
        return sum(r.get("pnl_usd", 0.0) for r in rows)

    def stop_reason(self) -> str | None:
        """Motivo por el que NO se abren posiciones nuevas, o None."""
        if (self.dir / "STOP").exists():
            return "STOP manual"
        if self.p.panic:
            return "panic"
        if not self.p.trading_enabled:
            return "trading_enabled=false"
        if len(self.positions) >= self.p.max_open:
            return f"{len(self.positions)} posiciones abiertas (máx {self.p.max_open})"
        n = len(self.closed())
        if n >= self.p.max_trades:
            self._auto_stop(f"corte: {n} operaciones cerradas"); return "corte por cantidad de operaciones"
        tot = self.realized_usd()
        if tot <= -abs(self.p.total_loss_usd):
            self._auto_stop(f"corte: pérdida total US${-tot:.0f}"); return "corte por pérdida total"
        today = self.realized_usd(ba_day())
        if today <= -abs(self.p.daily_loss_usd):
            return f"pérdida del día US${-today:.0f} (máx {self.p.daily_loss_usd:.0f}); reabre mañana"
        return None

    def _auto_stop(self, why: str) -> None:
        f = self.dir / "STOP"
        if not f.exists():
            f.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {why}\n")
            log.warning("STOP automático: %s", why)

    # ---------- ciclo de vida ----------
    def open(self, f: Fill, symbol: str, sol_usd: float) -> Position:
        pos = Position(mint=f.mint, symbol=symbol, opened_ts=time.time(), entry_price=f.price, tokens=f.tokens,
                       tokens_initial=f.tokens, sol_in=f.sol, peak_price=f.price, sol_usd_at_open=sol_usd,
                       last_price=f.price, last_ts=time.time())
        self.positions[f.mint] = pos
        self.save()
        return pos

    def exit_decision(self, pos: Position, px: float, now: float) -> tuple[str | None, float]:
        """(motivo, fracción de los tokens INICIALES a vender) o (None, 0)."""
        if px <= 0:
            return None, 0.0
        if self.p.panic:
            return "panic", 1.0
        if px <= pos.entry_price * (1 - self.p.stop):
            return "stop", 1.0
        if pos.peak_price > pos.entry_price and px <= pos.peak_price * (1 - self.p.trail):
            return "trailing", 1.0
        if not pos.tp_done and px >= pos.entry_price * self.p.tp_mult:
            return f"tp{self.p.tp_mult:g}x", self.p.tp_frac
        hold_s = self.p.factory_max_hold_s if self.p.strategy == "factory" else self.p.max_hold_min * 60
        if now - pos.opened_ts >= hold_s:
            return "tiempo", 1.0
        return None, 0.0

    def apply_sell(self, pos: Position, f: Fill, why: str) -> bool:
        """Registra una venta; devuelve True si la posición quedó cerrada."""
        pos.tokens = max(0.0, pos.tokens - f.tokens)
        pos.sol_out += f.sol
        pos.exits.append({"ts": time.time(), "why": why, "tokens": f.tokens, "sol": f.sol, "price": f.price, "sig": f.sig})
        if why.startswith("tp"):
            pos.tp_done = True
        closed = pos.tokens <= pos.tokens_initial * 0.001 or why in ("stop", "trailing", "tiempo", "panic")
        if closed:
            self._close(pos)
        self.save()
        return closed

    def _close(self, pos: Position) -> None:
        pnl_sol = pos.sol_out - pos.sol_in
        pnl_usd = pnl_sol * pos.sol_usd_at_open
        row = {"ts": time.time(), "day": ba_day(), "mint": pos.mint, "symbol": pos.symbol, "opened_ts": pos.opened_ts,
               "hold_min": round((time.time() - pos.opened_ts) / 60, 1), "sol_in": pos.sol_in, "sol_out": pos.sol_out,
               "pnl_sol": round(pnl_sol, 6), "pnl_usd": round(pnl_usd, 2), "ret": round(pos.sol_out / pos.sol_in - 1, 4) if pos.sol_in else 0,
               "peak_mult": round(pos.peak_price / pos.entry_price, 2) if pos.entry_price else 0,
               "exits": [e["why"] for e in pos.exits], "leftover_tokens": pos.tokens}
        self._append("closed.jsonl", row)
        self.positions.pop(pos.mint, None)
        log.info("CERRADA %s ret=%+.1f%% pnl=US$%+.2f salidas=%s", pos.symbol, row["ret"] * 100, pnl_usd, row["exits"])

    # ---------- resumen ----------
    def summary(self, extra: dict) -> dict:
        closed = self.closed()
        wins = [r for r in closed if r["pnl_usd"] > 0]
        s = {"ts": time.time(), "mode": self.p.mode, "open": len(self.positions),
             "closed": len(closed), "wins": len(wins), "hit_rate": round(len(wins) / len(closed), 3) if closed else None,
             "pnl_usd_total": round(sum(r["pnl_usd"] for r in closed), 2),
             "pnl_usd_today": round(self.realized_usd(ba_day()), 2),
             "ret_per_usd": round(sum(r["ret"] for r in closed), 3),
             "stop_reason": self.stop_reason(),
             "positions": [{"symbol": x.symbol, "mint": x.mint, "age_min": round((time.time() - x.opened_ts) / 60, 1), "age_s": int(time.time() - x.opened_ts),
                            "sol_in": round(x.sol_in, 4), "value_sol": round(x.tokens * (x.last_price or 0) + x.sol_out, 4), "last_ts": x.last_ts,
                            "mult": round(x.mult(x.last_price), 2), "peak_mult": round(x.mult(x.peak_price), 2),
                            "size_usd": round(x.size_usd, 2), "tp_done": x.tp_done} for x in self.positions.values()],
             "last_closed": closed[-10:][::-1], **extra}
        tmp = self.dir / "live_summary.json.tmp"
        json.dump(s, open(tmp, "w"), indent=1)
        tmp.replace(self.dir / "live_summary.json")
        return s
