"""Guardas operativas (26/10/2026), ideas tomadas del artículo "AI Trading Desk" (Jev) pero todo en código:

1) Banco de rechazos por motivo: un token rechazado queda en el banco un tiempo que depende del MOTIVO
   (perdimos con stop -> 60 min; "precio corrido" -> 2 min). Persistente en state/bench.json.
2) "No operar también es un resultado": contadores de rechazos por motivo del día, para ver qué filtro dispara.
3) Salida por falta de datos: lo decide el bot (posición sin precio fresco + 2 consultas fallidas -> se cierra).
4) Escalera de fallas: fallas de ejecución seguidas -> STOP y alerta; fuente de señales caída -> salir de las copias.
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter, deque
from pathlib import Path

log = logging.getLogger("live.guard")

# minutos que un token queda en el banco según el motivo (editable en control.json -> bench_min)
DEFAULT_BENCH_MIN = {
    "stop": 60,              # ya perdimos con stop en este token: no volver a entrar enseguida
    "sin_datos": 60,         # salimos porque no había precio: token raro
    "fuente_caida": 0,       # no es culpa del token
    "mcap_alto": 30,
    "compra_fallida": 10,    # sin ruta / swap roto
    "precio_corrido": 2,     # la cotización vino >X% arriba: puede normalizarse rápido
}


def reason_key(decision: str) -> str:
    """Normaliza un texto de decisión ('seguidor: mcap alto', 'compra fallida: ...') a una clave corta."""
    d = (decision or "").lower()
    if d.startswith("compra fallida"):
        return "precio_corrido" if "precio cotizado" in d else "compra_fallida"
    if "mcap alto" in d: return "mcap_alto"
    if "mcap muy chico" in d: return "mcap_chico"
    if d.startswith("freno"): return "freno"
    if d.startswith("sin saldo"): return "sin_saldo"
    if d.startswith("banco"): return "en_banco"
    if d.startswith("comprado"): return "comprado"
    return d.split(":")[0].strip().replace(" ", "_")[:40] or "otro"


class Bench:
    def __init__(self, state_dir: Path, minutes: dict | None = None):
        self.f = Path(state_dir) / "bench.json"
        self.minutes = {**DEFAULT_BENCH_MIN, **(minutes or {})}
        self.rows: dict[str, dict] = {}
        try:
            if self.f.exists():
                self.rows = json.load(open(self.f))
        except Exception:  # noqa: BLE001
            self.rows = {}

    def add(self, mint: str, key: str, now: float | None = None) -> None:
        mins = float(self.minutes.get(key, 0) or 0)
        if mins <= 0:
            return
        now = now or time.time()
        until = now + mins * 60
        cur = self.rows.get(mint)
        if cur and cur["until"] >= until:
            return
        self.rows[mint] = {"until": until, "why": key, "ts": now}
        self._save(now)

    def check(self, mint: str, now: float | None = None) -> str | None:
        r = self.rows.get(mint)
        if not r:
            return None
        if (now or time.time()) >= r["until"]:
            self.rows.pop(mint, None)
            return None
        return r["why"]

    def _save(self, now: float) -> None:
        self.rows = {m: r for m, r in self.rows.items() if r["until"] > now}
        tmp = self.f.with_suffix(".tmp")
        json.dump(self.rows, open(tmp, "w"))
        tmp.replace(self.f)


class Ladder:
    """Escalera de fallas. No decide trades: cuenta y avisa; el bot aplica la acción."""

    def __init__(self):
        self.exec_fails: deque = deque(maxlen=50)     # timestamps de fallas de ejecución seguidas (se vacía con un fill ok)
        self.sell_fails: Counter = Counter()          # mint -> ventas fallidas seguidas
        self.source_down_since: float = 0.0
        self.alerts: deque = deque(maxlen=15)

    def alert(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        if self.alerts and self.alerts[-1].endswith(msg):
            return
        self.alerts.append(f"{stamp} {msg}")
        log.warning("ALERTA: %s", msg)

    @staticmethod
    def counts_as_failure(error: str) -> bool:
        e = (error or "").lower()
        # el guardia de precio y "sin tokens" no son fallas de la cañería
        return bool(e) and "precio cotizado" not in e and "sin tokens" not in e

    def on_fill(self, ok: bool, side: str, mint: str, error: str, now: float) -> None:
        if ok:
            self.exec_fails.clear()
            if side == "sell":
                self.sell_fails.pop(mint, None)
            return
        if side == "sell":
            self.sell_fails[mint] += 1
        if self.counts_as_failure(error):
            self.exec_fails.append(now)

    def exec_fail_burst(self, n: int, window_s: float, now: float) -> int:
        k = sum(1 for t in self.exec_fails if now - t <= window_s)
        return k if k >= n else 0

    def source(self, connected: bool, now: float) -> float:
        """Segundos que lleva caída la fuente de señales (0 si está arriba)."""
        if connected:
            if self.source_down_since:
                self.alert(f"fuente de señales recuperada tras {now - self.source_down_since:.0f} s")
            self.source_down_since = 0.0
            return 0.0
        if not self.source_down_since:
            self.source_down_since = now
        return now - self.source_down_since


class RejectionLog:
    """Contadores del día (hora BA) por motivo: qué filtro está disparando."""

    def __init__(self):
        self.day = ""
        self.counts: Counter = Counter()

    def add(self, decision: str, day: str) -> None:
        if day != self.day:
            self.day, self.counts = day, Counter()
        self.counts[reason_key(decision)] += 1

    def snapshot(self) -> dict:
        tot = sum(self.counts.values())
        bought = self.counts.get("comprado", 0)
        return {"day": self.day, "seen": tot, "bought": bought, "by_reason": dict(self.counts.most_common()),
                "note": ("el filtro no rechaza nada: revisar" if tot >= 20 and bought == tot else
                         "rechaza todo: revisar si el filtro está muy cerrado" if tot >= 30 and bought == 0 else "")}
