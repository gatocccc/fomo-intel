"""Historia de precio por minuto de lanzamientos (Solana Tracker GET /chart/{mint}).

Se baja desde la creación del token hasta N horas después y se guarda en
data/charts/<mint>.json como lista de velas {t, o, h, l, c, v} (t en segundos).
1 request por token. No se vuelve a bajar lo que ya está guardado.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BASE = "https://data.solanatracker.io"


class QuotaExhausted(RuntimeError):
    pass


def select_tokens(launches: list, dead_threshold: float = -90.0, good_threshold: float = 50.0) -> tuple[list, list]:
    """Devuelve (buenos, muertos) entre los graduados, con la misma regla del análisis offline."""
    good, dead = [], []
    for L in launches:
        if not L.graduated:
            continue
        r = (L.returns.get("24h") or {}).get("chg")
        if r is not None and r > good_threshold:
            good.append(L)
        elif L.rugged or (r is not None and r <= dead_threshold):
            dead.append(L)
    return good, dead


class ChartFetcher:
    def __init__(self, api_key: str, data_dir: str, sleep_s: float = 0.4):
        if not api_key:
            raise ValueError("SOLANATRACKER_API_KEY vacío")
        self.h = {"x-api-key": api_key}
        self.sleep = sleep_s
        self.dir = Path(data_dir) / "charts"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.requests_made = 0

    def _get(self, path: str, **params):
        r = requests.get(f"{BASE}{path}", headers=self.h, params=params, timeout=30)
        self.requests_made += 1
        time.sleep(self.sleep)
        if r.status_code == 429:
            time.sleep(5)
            r = requests.get(f"{BASE}{path}", headers=self.h, params=params, timeout=30)
            self.requests_made += 1
        if r.status_code == 403:
            raise QuotaExhausted(f"403 en {path}: cuota de Solana Tracker agotada")
        r.raise_for_status()
        return r.json()

    def have(self, mint: str) -> bool:
        return (self.dir / f"{mint}.json").exists()

    def fetch(self, mint: str, created_ts: int, hours: float = 6.0, force: bool = False) -> list[dict]:
        p = self.dir / f"{mint}.json"
        if p.exists() and not force:
            return json.load(open(p))["candles"]
        if p.exists():   # conservar la versión anterior para detectar revisiones de la API
            prev_dir = self.dir / "_prev"; prev_dir.mkdir(exist_ok=True)
            prev_dir.joinpath(f"{mint}.json").write_text(p.read_text())
        t_from = max(0, created_ts - 60)
        t_to = created_ts + int(hours * 3600)
        d = self._get(f"/chart/{mint}", type="1m", time_from=t_from, time_to=t_to)
        raw = d.get("oclhv") if isinstance(d, dict) else d
        candles = []
        for c in raw or []:
            t = int(c.get("time") or 0)
            if t > 1e11:
                t //= 1000
            candles.append({"t": t, "o": float(c.get("open") or 0), "h": float(c.get("high") or 0),
                            "l": float(c.get("low") or 0), "c": float(c.get("close") or 0),
                            "v": float(c.get("volume") or 0)})
        candles.sort(key=lambda x: x["t"])
        json.dump({"mint": mint, "created_ts": created_ts, "hours": hours, "fetched_ts": int(time.time()),
                   "candles": candles}, open(p, "w"))
        return candles

    def load_all(self) -> dict[str, dict]:
        return {p.stem: json.load(open(p)) for p in self.dir.glob("*.json")}
