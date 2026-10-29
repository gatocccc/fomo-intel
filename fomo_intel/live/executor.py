"""Ejecución de compras y ventas.

RealExecutor: cotiza y arma la transacción con la Swap API de Solana Tracker
(GET https://swap-v2.solanatracker.io/swap), la firma localmente con la clave del servidor y la
envía por el RPC de Helius. Después lee la transacción confirmada para registrar el precio REAL
(lo que de verdad entró y salió de la billetera), que es lo que se compara con el esperado para
medir el slippage verdadero.

Pases de efectivo (SOL<->USDC/USDT): primero por la Swap API de Jupiter, que no cobra comisión de plataforma
(Solana Tracker cobra 0,5% por lado y en plomería interna era puro costo); si Jupiter falla, Solana Tracker como siempre.
Se apaga con JUP_STABLE_SWAPS=0.

PaperExecutor: mismas interfaces; simula el fill al precio del stream con slippage y fee fijos.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field

import requests

from .config import SOL_MINT, LiveParams

log = logging.getLogger("live.exec")
SWAP_URL = "https://swap-v2.solanatracker.io/swap"
PUMPPORTAL_LOCAL = "https://pumpportal.fun/api/trade-local"   # segunda vía: transacción directa contra pump.fun/PumpSwap (0,5% fee)
# Pases SOL<->USDC/USDT por la Swap API de Jupiter: sin comisión de plataforma (Solana Tracker cobra 0,5% por lado, que en
# plomería interna del libro —estacionar y desestacionar efectivo— era puro costo). Con JUPITER_API_KEY va a api.jup.ag; sin clave, lite-api.
STABLE_MINTS = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6}
JUP_SWAP_ON = os.getenv("JUP_STABLE_SWAPS", "1") == "1"
JUP_KEY = os.getenv("JUPITER_API_KEY", "")
JUP_BASE = "https://api.jup.ag/swap/v1" if JUP_KEY else "https://lite-api.jup.ag/swap/v1"


def jup_swap_tx(frm: str, to: str, amount_raw: int, slippage_pct: float, payer: str, priority_fee_sol: float) -> tuple[str, dict]:
    """Cotiza y arma (sin firmar) un swap por Jupiter. Devuelve (transacción base64 v0, cotización)."""
    h = {"x-api-key": JUP_KEY} if JUP_KEY else {}
    q = requests.get(f"{JUP_BASE}/quote", params={"inputMint": frm, "outputMint": to, "amount": int(amount_raw), "slippageBps": int(slippage_pct * 100),
                                                   "restrictIntermediateTokens": "true"}, headers=h, timeout=15)
    if q.status_code >= 400:
        raise RuntimeError(f"jup quote {q.status_code}: {q.text[:160]}")
    quote = q.json()
    body = {"quoteResponse": quote, "userPublicKey": payer, "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": int(max(priority_fee_sol, 0.0001) * 1e9), "priorityLevel": "medium"}}}
    s = requests.post(f"{JUP_BASE}/swap", json=body, headers=h, timeout=20)
    if s.status_code >= 400 or not (s.json() or {}).get("swapTransaction"):
        raise RuntimeError(f"jup swap {s.status_code}: {s.text[:160]}")
    return s.json()["swapTransaction"], quote


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


def impact_pct(rate: dict) -> float:
    """Impacto REAL de la cotización: cuánto peor es el precio efectivo (amountIn/amountOut) que el precio
    actual que informa la propia API (currentPrice, en tokens por SOL). El campo priceImpact de la API no es
    confiable (mide otra cosa: dio 10-30% en compras de US$10 cuyo precio efectivo estaba a ±3% del mercado)."""
    try:
        ai = float(rate.get("amountIn") or 0); ao = float(rate.get("amountOut") or 0); cur = float(rate.get("currentPrice") or 0)
        if ai > 0 and ao > 0 and cur > 0:
            return max(0.0, (1 - ao / (cur * ai)) * 100)
    except (TypeError, ValueError):
        pass
    v = float(rate.get("priceImpact") or 0)
    return v * 100 if v < 1.5 else v


def real_quote(frm: str, to: str, amount, slippage_pct: float, payer: str, priority_fee: float, api_key: str = "", tries: int = 3) -> dict:
    params = {"from": frm, "to": to, "fromAmount": amount, "slippage": slippage_pct, "payer": payer,
              "priorityFee": priority_fee, "txVersion": "v0"}
    last = ""
    for i in range(tries):
        r = requests.get(SWAP_URL, params=params, headers={"x-api-key": api_key} if api_key else {}, timeout=20)
        if r.status_code < 400:
            return r.json()
        last = f"swap api {r.status_code}: {r.text[:200]}"
        time.sleep(0.4 * (i + 1))        # los 500 "Failed to swap" en tokens recién creados son intermitentes
    raise RuntimeError(last)


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
            f.quote_impact_pct = round(impact_pct(rate), 2)
            f.raw = {"rate": rate, "type": q.get("type") or q.get("txVersion")}
        except Exception as e:  # noqa: BLE001
            f.raw = {"quote_error": str(e)[:200]}

    def buy(self, mint: str, sol_amount: float, ref_price: float, fast: bool = False) -> Fill:
        px = ref_price * (1 + self.p.paper_slippage) * (1 + self.p.paper_fee)
        f = Fill(True, "buy", mint, sol=sol_amount, tokens=sol_amount / px, price=px, expected_price=ref_price,
                 slippage_pct=round((px / ref_price - 1) * 100, 2), sig=f"paper-{int(time.time()*1000)}")
        self._try_quote(f, SOL_MINT, mint, round(sol_amount, 6))
        # mismo guardia que en real: si el impacto cotizado supera el máximo, en vivo NO habríamos comprado
        if f.quote_impact_pct and f.quote_impact_pct > self.p.max_slippage_pct:
            f.ok = False; f.error = f"impacto {f.quote_impact_pct:.1f}% > {self.p.max_slippage_pct}%"
        elif f.quote_impact_pct:
            # fill simulado al precio de ejecución cotizado (más realista que slippage fijo)
            rate = f.raw.get("rate") or {}
            try:
                tokens_out = float(rate.get("amountOut") or 0)
                if tokens_out > 0:
                    f.tokens = tokens_out; f.price = sol_amount / tokens_out
                    f.slippage_pct = round((f.price / ref_price - 1) * 100, 2) if ref_price else 0.0
            except (TypeError, ValueError):
                pass
        return f

    def sell(self, mint: str, tokens: float, ref_price: float, fast: bool = False) -> Fill:
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
        return real_quote(frm, to, amount, slippage_pct, self.pub, self.p.priority_fee_sol, self.h.get("x-api-key", ""))

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

    def _pumpportal_tx(self, side: str, mint: str, amount, slippage_pct: float) -> str:
        """Pide a PumpPortal la transacción ya armada (sin firmar). amount: SOL si compra; tokens o "100%" si venta."""
        body = {"publicKey": self.pub, "action": side, "mint": mint, "amount": amount,
                "denominatedInSol": "true" if side == "buy" else "false", "slippage": int(slippage_pct),
                "priorityFee": self.p.priority_fee_sol, "pool": "auto"}
        r = requests.post(PUMPPORTAL_LOCAL, json=body, timeout=20)
        if r.status_code != 200 or not r.content:
            raise RuntimeError(f"pumpportal {r.status_code}: {r.text[:200]}")
        return base64.b64encode(r.content).decode()

    def _execute(self, side: str, mint: str, frm: str, to: str, amount, ref_price: float, fast: bool = False) -> Fill:
        t0 = time.time()
        f = Fill(False, side, mint, expected_price=ref_price)
        txn_b64, version, via = None, "v0", "solanatracker"
        if JUP_SWAP_ON and mint in STABLE_MINTS and not fast:
            # pase de efectivo (SOL<->stable): Jupiter, sin comisión de plataforma; slippage corto porque el par es profundo
            try:
                dec = STABLE_MINTS[mint]
                if side == "buy":
                    raw_amt = int(round(float(amount) * 1e9))
                elif amount == "auto":
                    raw_amt, _ = self.rpc.token_balance(self.pub, mint)
                else:
                    raw_amt = int(round(float(amount) * 10 ** dec))
                if raw_amt <= 0:
                    raise RuntimeError("monto cero")
                txn_b64, quote = jup_swap_tx(frm, to, raw_amt, 1.0, self.pub, self.p.priority_fee_sol)
                via = "jupiter"
                ai = float(quote.get("inAmount") or 0); ao = float(quote.get("outAmount") or 0)
                f.quote_impact_pct = round(float(quote.get("priceImpactPct") or 0) * 100, 3)
                f.raw = {"via": via, "rate": {"amountIn": ai / (1e9 if side == "buy" else 10 ** dec), "amountOut": ao / (10 ** dec if side == "buy" else 1e9),
                                              "priceImpact": quote.get("priceImpactPct"), "route": [r.get("swapInfo", {}).get("label") for r in quote.get("routePlan") or []]}}
            except Exception as e:  # noqa: BLE001
                log.warning("jupiter %s %s: %s; voy por Solana Tracker", side, mint[:6], e)
                txn_b64, via = None, "solanatracker"; f.raw = {"jup_error": str(e)[:160]}
        if not txn_b64:
            try:
                if fast:
                    raise RuntimeError("modo rápido: directo a PumpPortal")
                q = self.quote(frm, to, amount, self.p.swap_slippage_pct)
                rate = q.get("rate") or {}
                f.quote_impact_pct = round(impact_pct(rate), 2)
                f.raw = {"rate": rate, "type": q.get("type") or q.get("txVersion"), "via": via}
                # guardia real: precio efectivo de la cotización contra el precio de referencia fresco
                try:
                    ai = float(rate.get("amountIn") or 0); ao = float(rate.get("amountOut") or 0)
                    if side == "buy" and ai > 0 and ao > 0 and ref_price > 0:
                        eff = ai / ao
                        f.quote_impact_pct = round((eff / ref_price - 1) * 100, 2)
                except (TypeError, ValueError):
                    pass
                if side == "buy" and f.quote_impact_pct > self.p.max_slippage_pct:
                    f.error = f"precio cotizado {f.quote_impact_pct:+.1f}% vs referencia (máx {self.p.max_slippage_pct}%)"; return f
                txn_b64, version = q["txn"], (q.get("type") or q.get("txVersion") or "v0")
            except Exception as e:  # noqa: BLE001
                # segunda vía: PumpPortal arma la transacción directo contra la curva / PumpSwap
                try:
                    pp_amount = amount if side == "buy" else ("100%" if amount == "auto" else amount)
                    txn_b64 = self._pumpportal_tx(side, mint, pp_amount, max(self.p.swap_slippage_pct, 15))
                    via = "pumpportal"; f.raw = {"via": via, "st_error": str(e)[:160]}
                except Exception as e2:  # noqa: BLE001
                    f.error = f"cotización: {str(e)[:120]} | pumpportal: {str(e2)[:120]}"; return f
        try:
            signed = self._sign(txn_b64, version)
            # además del RPC, mandar la misma transacción firmada al block engine de Jito (en paralelo, sin esperar)
            try:
                import threading
                threading.Thread(target=lambda: requests.post("https://mainnet.block-engine.jito.wtf/api/v1/transactions",
                                 json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [signed, {"encoding": "base64"}]}, timeout=5), daemon=True).start()
            except Exception:  # noqa: BLE001
                pass
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

    def buy(self, mint: str, sol_amount: float, ref_price: float, fast: bool = False) -> Fill:
        return self._execute("buy", mint, SOL_MINT, mint, round(sol_amount, 6), ref_price, fast=fast)

    def sell(self, mint: str, tokens: float, ref_price: float, fast: bool = False) -> Fill:
        raw, dec = self.rpc.token_balance(self.pub, mint)
        have = raw / (10 ** dec)
        if have <= 0:
            return Fill(False, "sell", mint, expected_price=ref_price, error="sin tokens en la billetera")
        amt = round(min(tokens, have), dec)
        if tokens >= have * 0.98:
            f = self._execute("sell", mint, mint, SOL_MINT, "auto", ref_price, fast=fast)   # vende todo lo que haya
            if f.ok or not f.error.startswith("cotización"):
                return f
            amt = round(have, dec)
        return self._execute("sell", mint, mint, SOL_MINT, amt, ref_price, fast=fast)

    def token_balance(self, mint: str) -> float | None:
        try:
            raw, dec = self.rpc.token_balance(self.pub, mint)
            return raw / (10 ** dec)
        except Exception:  # noqa: BLE001
            return None

    def sol_balance(self) -> float:
        return self.rpc.sol_balance(self.pub)
