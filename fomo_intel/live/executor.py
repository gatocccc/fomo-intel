"""Ejecución de compras y ventas.

RealExecutor: cotiza y arma la transacción con la Swap API de Solana Tracker
(GET https://swap-v2.solanatracker.io/swap), la firma localmente con la clave del servidor y la
envía por el RPC de Helius. Después lee la transacción confirmada para registrar el precio REAL
(lo que de verdad entró y salió de la billetera), que es lo que se compara con el esperado para
medir el slippage verdadero.

PaperExecutor: mismas interfaces; simula el fill al precio del stream con slippage y fee fijos.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field

import requests

from .config import SOL_MINT, LiveParams

log = logging.getLogger("live.exec")
SWAP_URL = "https://swap-v2.solanatracker.io/swap"


@dataclass
class Fill:
    ok: bool
    side: str                   # buy | sell
    mint: str
    sol: float = 0.0            # SOL gastados (buy) o recibidos (sell), neto de fees de red
    tokens: float = 0.0         # tokens recibidos (buy) o vendidos (sell)
    price: float = 0.0          # SOL por token efectivo
    expected_price: float = 0.0 # precio de referencia al decidir
    slippage_pct: float = 0.0   # (price/expected - 1) * 100, positivo = pagamos más / cobramos menos
    quote_impact_pct: float = 0.0
    sig: str = ""
    error: str = ""
    latency_s: float = 0.0
    raw: dict = field(default_factory=dict)


def real_quote(frm: str, to: str, amount, slippage_pct: float, payer: str, priority_fee: float, api_key: str = "") -> dict:
    params = {"from": frm, "to": to, "fromAmount": amount, "slippage": slippage_pct, "payer": payer,
              "priorityFee": priority_fee, "txVersion": "v0"}
    r = requests.get(SWAP_URL, params=params, headers={"x-api-key": api_key} if api_key else {}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"swap api {r.status_code}: {r.text[:300]}")
    return r.json()


class PaperExecutor:
    """Simula el fill; si tiene una billetera (aunque esté vacía) pide ADEMÁS la cotización real
    al swap para registrar el impacto de precio que habríamos tenido. No firma ni envía nada."""
    mode = "paper"

    def __init__(self, p: LiveParams, payer: str = "", st_api_key: str = ""):
        self.p = p
        self.payer = payer
        self.api_key = st_api_key

    def _try_quote(self, f: Fill, frm: str, to: str, amount) -> None:
        if not self.payer:
            return
        try:
            q = real_quote(frm, to, amount, self.p.swap_slippage_pct, self.payer, self.p.priority_fee_sol, self.api_key)
            rate = q.get("rate") or {}
            f.quote_impact_pct = float(rate.get("priceImpact") or 0)
            f.raw = {"rate": rate, "type": q.get("type") or q.get("txVersion"), "keys": sorted(q.keys())}
        except Exception as e:  # noqa: BLE001
            f.raw = {"quote_error": str(e)[:200]}

    def buy(self, mint: str, sol_amount: float, ref_price: float) -> Fill:
        px = ref_price * (1 + self.p.paper_slippage) * (1 + self.p.paper_fee)
        f = Fill(True, "buy", mint, sol=sol_amount, tokens=sol_amount / px, price=px, expected_price=ref_price,
                 slippage_pct=round((px / ref_price - 1) * 100, 2), sig=f"paper-{int(time.time()*1000)}")
        self._try_quote(f, SOL_MINT, mint, round(sol_amount, 6))
        return f

    def sell(self, mint: str, tokens: float, ref_price: float) -> Fill:
        px = ref_price * (1 - self.p.paper_slippage) * (1 - self.p.paper_fee)
        f = Fill(True, "sell", mint, sol=tokens * px, tokens=tokens, price=px, expected_price=ref_price,
                 slippage_pct=round((1 - px / ref_price) * 100, 2), sig=f"paper-{int(time.time()*1000)}")
        # la cotización de venta real fallaría (no tenemos los tokens); solo se mide en la compra
        return f

    def token_balance(self, mint: str) -> float | None:
        return None   # el portfolio lleva la cuenta


class RealExecutor:
    mode = "real"

    def __init__(self, p: LiveParams, keypair, rpc, st_api_key: str = ""):
        self.p = p
        self.kp = keypair
        self.pub = str(keypair.pubkey())
        self.rpc = rpc
        self.h = {"x-api-key": st_api_key} if st_api_key else {}

    # ---------- cotización ----------
    def quote(self, frm: str, to: str, amount, slippage_pct: float) -> dict:
        params = {"from": frm, "to": to, "fromAmount": amount, "slippage": slippage_pct, "payer": self.pub,
                  "priorityFee": self.p.priority_fee_sol, "txVersion": "v0"}
        r = requests.get(SWAP_URL, params=params, headers=self.h, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"swap api {r.status_code}: {r.text[:300]}")
        return r.json()

    # ---------- firma y envío ----------
    def _sign(self, txn_b64: str, version: str) -> str:
        raw = base64.b64decode(txn_b64)
        if (version or "").lower() in ("v0", "0", "versioned"):
            from solders.message import to_bytes_versioned
            from solders.transaction import VersionedTransaction
            tx = VersionedTransaction.from_bytes(raw)
            sig = self.kp.sign_message(to_bytes_versioned(tx.message))
            signed = VersionedTransaction.populate(tx.message, [sig])
            return base64.b64encode(bytes(signed)).decode()
        from solders.transaction import Transaction
        tx = Transaction.from_bytes(raw)
        tx.sign([self.kp], tx.message.recent_blockhash)
        return base64.b64encode(bytes(tx)).decode()

    def _execute(self, side: str, mint: str, frm: str, to: str, amount, ref_price: float) -> Fill:
        t0 = time.time()
        f = Fill(False, side, mint, expected_price=ref_price)
        try:
            q = self.quote(frm, to, amount, self.p.swap_slippage_pct)
        except Exception as e:  # noqa: BLE001
            f.error = f"cotización: {e}"; return f
        rate = q.get("rate") or {}
        f.quote_impact_pct = float(rate.get("priceImpact") or 0)
        f.raw = {"rate": rate, "type": q.get("type") or q.get("txVersion")}
        if side == "buy" and f.quote_impact_pct > self.p.max_slippage_pct:
            f.error = f"impacto {f.quote_impact_pct:.1f}% > {self.p.max_slippage_pct}%"; return f
        try:
            signed = self._sign(q["txn"], q.get("type") or q.get("txVersion") or "v0")
            sig = self.rpc.send_raw(signed)
            f.sig = sig
            st = self.rpc.wait_confirmed(sig, timeout=75)
            if not st:
                f.error = "sin confirmación en 75 s"; f.latency_s = round(time.time() - t0, 1); return f
            det = self.rpc.fill_details(sig, self.pub, mint)
        except Exception as e:  # noqa: BLE001
            f.error = str(e)[:300]; f.latency_s = round(time.time() - t0, 1); return f
        f.latency_s = round(time.time() - t0, 1)
        f.raw["fill"] = det
        sol_d, tok_d = det.get("sol_delta", 0.0), det.get("token_delta", 0.0)
        if side == "buy":
            f.sol, f.tokens = -sol_d, tok_d
        else:
            f.sol, f.tokens = sol_d, -tok_d
        if f.tokens <= 0 or f.sol <= 0:
            f.error = f"fill raro: sol={sol_d} tokens={tok_d}"; return f
        f.price = f.sol / f.tokens
        if ref_price > 0:
            f.slippage_pct = round(((f.price / ref_price - 1) if side == "buy" else (1 - f.price / ref_price)) * 100, 2)
        f.ok = True
        return f

    def buy(self, mint: str, sol_amount: float, ref_price: float) -> Fill:
        return self._execute("buy", mint, SOL_MINT, mint, round(sol_amount, 6), ref_price)

    def sell(self, mint: str, tokens: float, ref_price: float) -> Fill:
        raw, dec = self.rpc.token_balance(self.pub, mint)
        have = raw / (10 ** dec)
        if have <= 0:
            return Fill(False, "sell", mint, expected_price=ref_price, error="sin tokens en la billetera")
        amt = round(min(tokens, have), dec)
        if tokens >= have * 0.98:
            f = self._execute("sell", mint, mint, SOL_MINT, "auto", ref_price)   # vende todo lo que haya
            if f.ok or not f.error.startswith("cotización"):
                return f
            amt = round(have, dec)
        return self._execute("sell", mint, mint, SOL_MINT, amt, ref_price)

    def token_balance(self, mint: str) -> float | None:
        try:
            raw, dec = self.rpc.token_balance(self.pub, mint)
            return raw / (10 ** dec)
        except Exception:  # noqa: BLE001
            return None

    def sol_balance(self) -> float:
        return self.rpc.sol_balance(self.pub)
