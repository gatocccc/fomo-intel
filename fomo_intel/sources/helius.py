"""Cliente Helius (Solana): historial de transacciones parseadas y fuente de fondeo.

Docs: https://www.helius.dev/docs (Enhanced Transactions API, Wallet API).

Cómo se detecta un swap: FOMO rutea por OKX DEX Router y paga el gas por el usuario,
así que la wallet no mueve SOL y el evento `swap` de Helius viene vacío. Lo robusto es
netear, por mint, todo lo que la wallet envía y recibe en `tokenTransfers` (más SOL
nativo): pierde base (USDC/USDT/SOL) y gana un memecoin = compra; al revés = venta.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Iterable

import requests

from ..models import Trade, Transfer

BASE = "https://api.helius.xyz/v0"
STABLES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCdbeMoReleaseDF": "USDT",
}
WSOL = "So11111111111111111111111111111111111111112"
MIN_BASE_USD = 1.0       # swaps de menos de US$1 se ignoran (dust, fees)
MIN_TRANSFER_SOL = 0.01


class HeliusClient:
    def __init__(self, api_key: str, sol_price_usd: float = 150.0, sleep_s: float = 0.25):
        if not api_key:
            raise ValueError("HELIUS_API_KEY vacío")
        self.key = api_key
        self.sol_price = sol_price_usd
        self.sleep_s = sleep_s

    # ---------- HTTP ----------
    def _get(self, path: str, **params) -> list | dict:
        params["api-key"] = self.key
        r = requests.get(f"{BASE}{path}", params=params, timeout=30)
        r.raise_for_status()
        time.sleep(self.sleep_s)
        return r.json()

    def wallet_transactions(self, wallet: str, since_ts: int, max_pages: int = 50) -> list[dict]:
        """Pagina hacia atrás hasta `since_ts`. Devuelve transacciones parseadas por Helius."""
        out, before = [], None
        for _ in range(max_pages):
            params = {"limit": 100}
            if before:
                params["before"] = before
            page = self._get(f"/addresses/{wallet}/transactions", **params)
            if not page:
                break
            out.extend(page)
            if page[-1].get("timestamp", 0) < since_ts:
                break
            before = page[-1]["signature"]
        return [tx for tx in out if tx.get("timestamp", 0) >= since_ts]

    def funding_source(self, wallet: str) -> dict | None:
        try:
            return self._get(f"/addresses/{wallet}/funded-by")
        except requests.HTTPError:
            return None

    # ---------- normalización ----------
    def parse(self, wallet: str, txs: Iterable[dict]) -> tuple[list[Trade], list[Transfer]]:
        trades, transfers = [], []
        for tx in txs:
            sig, ts = tx.get("signature", ""), tx.get("timestamp", 0)
            t = self._parse_swap(wallet, tx, sig, ts)
            if t:
                trades.append(t)
                continue
            # No es swap: registrar transferencias relevantes (SOL y stables) con otras wallets
            for nt in tx.get("nativeTransfers", []):
                src, dst, lam = nt.get("fromUserAccount", ""), nt.get("toUserAccount", ""), nt.get("amount", 0)
                if lam / 1e9 >= MIN_TRANSFER_SOL and wallet in (src, dst) and src != dst:
                    transfers.append(Transfer(src=src, dst=dst, amount_usd=lam / 1e9 * self.sol_price, ts=ts, tx=sig))
            for tt in tx.get("tokenTransfers", []):
                mint, src, dst = tt.get("mint"), tt.get("fromUserAccount", ""), tt.get("toUserAccount", "")
                if mint in STABLES and wallet in (src, dst) and src != dst and float(tt.get("tokenAmount", 0)) >= MIN_BASE_USD:
                    transfers.append(Transfer(src=src, dst=dst, amount_usd=float(tt.get("tokenAmount", 0)),
                                              ts=ts, tx=sig, asset=STABLES[mint]))
        return trades, transfers

    def _parse_swap(self, wallet: str, tx: dict, sig: str, ts: int) -> Trade | None:
        net: dict[str, float] = defaultdict(float)   # mint -> cantidad neta para la wallet
        for tt in tx.get("tokenTransfers", []):
            amt = float(tt.get("tokenAmount", 0) or 0)
            mint = tt.get("mint", "")
            if tt.get("toUserAccount") == wallet:
                net[mint] += amt
            if tt.get("fromUserAccount") == wallet:
                net[mint] -= amt
        sol = 0.0
        for nt in tx.get("nativeTransfers", []):
            lam = nt.get("amount", 0) / 1e9
            if nt.get("toUserAccount") == wallet:
                sol += lam
            if nt.get("fromUserAccount") == wallet:
                sol -= lam
        base_usd = sum(v for m, v in net.items() if m in STABLES) + (net.get(WSOL, 0.0) + sol) * self.sol_price
        meme = {m: v for m, v in net.items() if m not in STABLES and m != WSOL and abs(v) > 0}
        if not meme or abs(base_usd) < MIN_BASE_USD:
            return None
        mint, qty = max(meme.items(), key=lambda kv: abs(kv[1]))
        if qty > 0 and base_usd < 0:
            side, usd = "buy", -base_usd
        elif qty < 0 and base_usd > 0:
            side, usd = "sell", base_usd
        else:
            return None          # airdrop, transferencia de token, o swap memecoin↔memecoin
        qty = abs(qty)
        return Trade(wallet=wallet, token=mint, side=side, amount_usd=usd, token_amount=qty,
                     ts=ts, tx=sig, price_usd=usd / qty)
