"""Cliente Solana Tracker Data API: leaderboard de wallets FOMO, trades por wallet,
precio histórico y metadatos de token (liquidez, fecha de creación).

Docs: https://docs.solanatracker.io  (los paths exactos pueden cambiar; ajustar acá).
"""
from __future__ import annotations

import time

import requests

from ..models import Trade

BASE = "https://data.solanatracker.io"


class SolanaTrackerClient:
    def __init__(self, api_key: str, sleep_s: float = 0.35):
        if not api_key:
            raise ValueError("SOLANATRACKER_API_KEY vacío")
        self.h = {"x-api-key": api_key}
        self.sleep_s = sleep_s

    def _get(self, path: str, **params) -> dict | list:
        r = requests.get(f"{BASE}{path}", headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        time.sleep(self.sleep_s)
        return r.json()

    def fomo_leaderboard(self, days: int = 30, limit: int = 50) -> list[dict]:
        """Top traders por PnL realizado. Si la API expone filtro por plataforma,
        se usa 'fomo'; si no, se filtra después por las wallets FOMO conocidas."""
        data = self._get("/v2/pnl/leaderboard/top", days=days, sort="realized",
                         direction="desc", limit=limit, platform="fomo")
        return data.get("traders", data) if isinstance(data, dict) else data

    def wallet_trades(self, wallet: str, since_ts: int) -> list[Trade]:
        out, cursor = [], None
        while True:
            params = {"limit": 500}
            if cursor:
                params["cursor"] = cursor
            data = self._get(f"/wallet/{wallet}/trades", **params)
            rows = data.get("trades", []) if isinstance(data, dict) else data
            for r in rows:
                ts = int(r.get("time", 0) / 1000) if r.get("time", 0) > 1e11 else int(r.get("time", 0))
                if ts < since_ts:
                    return out
                side = "buy" if r.get("type") == "buy" else "sell"
                tok = r.get("to", {}) if side == "buy" else r.get("from", {})
                qty = float(tok.get("amount", 0))
                usd = float(r.get("volume", {}).get("usd", 0) if isinstance(r.get("volume"), dict) else r.get("volume", 0))
                if qty > 0 and usd > 0:
                    out.append(Trade(wallet=wallet, token=tok.get("address", ""), side=side, amount_usd=usd,
                                     token_amount=qty, ts=ts, tx=r.get("tx", ""), price_usd=usd / qty))
            cursor = data.get("nextCursor") if isinstance(data, dict) else None
            if not cursor:
                return out

    def token_meta(self, token: str) -> dict:
        d = self._get(f"/tokens/{token}")
        pools = d.get("pools", [{}])
        liq = max((p.get("liquidity", {}).get("usd", 0) for p in pools), default=0)
        created = min((p.get("createdAt", 0) for p in pools if p.get("createdAt")), default=0)
        return {"liquidity_usd": liq, "created_ts": int(created / 1000) if created > 1e11 else int(created)}

    def price_history(self, token: str, start_ts: int, end_ts: int) -> list[tuple[int, float]]:
        d = self._get(f"/chart/{token}", type="1m", time_from=start_ts, time_to=end_ts)
        return [(int(c["time"]), float(c["close"])) for c in d.get("oclhv", [])]
