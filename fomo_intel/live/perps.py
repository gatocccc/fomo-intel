"""Cliente de Jupiter Perpetuals (Solana) para abrir y cerrar LONG/SHORT en SOL, BTC y ETH
desde la billetera propia del bot.

Usa la misma API que la app de Jupiter (https://perps-api.jup.ag/v1):
  - GET  /positions?walletAddress=W           → posiciones abiertas
  - GET  /market-stats?mint=M                 → precio y stats del mercado
  - POST /positions/increase                  → cotización + tx serializada para abrir/aumentar
  - POST /positions/decrease                  → cotización + tx para cerrar/reducir (on-chain)
  - POST /positions-gasless/decrease          → ídem, variante "gasless" (fallback)

Modelo de ejecución (hipótesis a verificar en el servidor, ver `open`):
  * transactionType "legacy": la API devuelve una transacción de *position request* común que sólo
    necesita la firma de la billetera; los keepers de Jupiter la cumplen on-chain. Camino preferido.
  * transactionType "instant" (default de la API): la tx exige 3 firmas (billetera + 2 keepers) y
    viene con el slot del keeper ya firmado. Firmamos nuestro slot preservando las firmas existentes
    y la mandamos igual; si falta una firma el RPC lo rechaza y lo registramos tal cual.

Dependencias: stdlib + requests + solders. No toca nada del resto del bot salvo `wallet.Rpc`.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

BASE_URL = "https://perps-api.jup.ag/v1"

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6

# Mints de mercado (el de BTC es el custody mint de wBTC que usa Jupiter perps)
MARKETS: dict[str, str] = {
    "SOL": "So11111111111111111111111111111111111111112",
    "ETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
    "BTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
}
MINT_TO_SYMBOL = {v: k for k, v in MARKETS.items()}
MINT_TO_SYMBOL[USDC] = "USDC"

# Cuentas de custodia (informativo / para parsear posiciones que vengan con custody en vez de mint)
CUSTODIES: dict[str, str] = {
    "SOL": "7xS2gz2bTp3fwCC7knJvUWTEU9Tycczu6VhJYKgi1wdz",
    "ETH": "AQCGyheWPLeo6Qp9WpYS9m3Qj479t7R636N9ey1rEjEn",
    "BTC": "5Pv3gM9JrFFH883SWAhvJC9RPYmo8UNxuFtv5bMMALkm",
    "USDC": "G18jKKXQwBbrHeiK3C9MRXhkHsLHf7XgCSisykV46EZa",
}
CUSTODY_TO_SYMBOL = {v: k for k, v in CUSTODIES.items()}

MAX_LEVERAGE = 3.0           # guardia dura: nunca más de 3x
MIN_SOL_FOR_FEES = 0.01      # aviso si la billetera tiene menos SOL que esto
CONFIRM_TIMEOUT_S = 90
HTTP_TIMEOUT_S = 30
HTTP_RETRIES = 4

_EMPTY_SIG = bytes(64)


class PerpsError(Exception):
    """Error de lógica del cliente (parámetros, saldo, etc.)."""


class PerpsApiError(PerpsError):
    """Respuesta 4xx de la API: `status` y `body` traen el mensaje verbatim."""

    def __init__(self, status: int, body: str, path: str):
        self.status, self.body, self.path = status, body, path
        super().__init__(f"HTTP {status} {path}: {body}")


def _f(x: Any, default: float | None = None) -> float | None:
    """Convierte a float tolerando None, strings numéricos y basura."""
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _first(d: dict, *keys: str, default=None):
    """Primer valor no nulo entre varias claves candidatas (la API cambia nombres)."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class JupPerps:
    """Cliente de alto nivel. `kp` es un solders Keypair, `rpc` un `wallet.Rpc`."""

    def __init__(self, kp, rpc, log: logging.Logger | None = None, base_url: str = BASE_URL):
        self.kp = kp
        self.rpc = rpc
        self.log = log or logging.getLogger("perps")
        self.base_url = base_url.rstrip("/")
        self.wallet = str(kp.pubkey())
        self.http = requests.Session()
        self.http.headers.update({"accept": "application/json", "content-type": "application/json",
                                  "user-agent": "fomo-intel-perps/0.1"})

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
        """GET/POST con timeout 30 s, reintentos con backoff en 429/5xx/red, y 4xx verbatim."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(HTTP_RETRIES):
            try:
                r = self.http.request(method, url, params=params, json=body, timeout=HTTP_TIMEOUT_S)
            except requests.RequestException as e:  # red / timeout
                last_err = e
                self.log.warning("perps http %s %s network error (try %d): %s", method, path, attempt + 1, e)
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                wait = float(r.headers.get("retry-after") or 1.5 * (attempt + 1))
                self.log.warning("perps http %s %s -> %d, retry in %.1fs", method, path, r.status_code, wait)
                time.sleep(min(wait, 15))
                continue
            if r.status_code >= 400:
                self.log.error("perps http %s %s -> %d: %s", method, path, r.status_code, r.text[:1000])
                raise PerpsApiError(r.status_code, r.text, path)
            if not r.content:
                return None
            try:
                return r.json()
            except ValueError:
                return r.text
        raise PerpsError(f"{method} {path} failed after {HTTP_RETRIES} tries: {last_err}")

    def _get(self, path: str, **params) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict) -> Any:
        self.log.debug("perps POST %s %s", path, json.dumps(body))
        return self._request("POST", path, body=body)

    # --------------------------------------------------------------- mercado
    @staticmethod
    def markets() -> dict[str, str]:
        """símbolo → mint de mercado."""
        return dict(MARKETS)

    @staticmethod
    def _mint(symbol: str) -> str:
        s = symbol.upper()
        if s not in MARKETS:
            raise PerpsError(f"unknown market {symbol!r}; valid: {', '.join(MARKETS)}")
        return MARKETS[s]

    def market_stats(self, symbol: str) -> dict:
        return self._get("market-stats", mint=self._mint(symbol)) or {}

    def price(self, symbol: str) -> float:
        st = self.market_stats(symbol)
        p = _f(_first(st, "price", "markPrice", "indexPrice"))
        if p is None:
            raise PerpsError(f"market-stats without price for {symbol}: {json.dumps(st)[:300]}")
        return p

    # ------------------------------------------------------------ posiciones
    def positions_raw(self) -> list[dict]:
        d = self._get("positions", walletAddress=self.wallet) or {}
        if isinstance(d, list):
            return d
        return list(_first(d, "dataList", "data", "positions", default=[]) or [])

    @classmethod
    def _symbol_of(cls, p: dict) -> str:
        mint = _first(p, "marketMint", "market", "mint", "tokenMint")
        if mint in MINT_TO_SYMBOL:
            return MINT_TO_SYMBOL[mint]
        cust = _first(p, "custody", "custodyPubkey", "custodyKey")
        if cust in CUSTODY_TO_SYMBOL:
            return CUSTODY_TO_SYMBOL[cust]
        return str(_first(p, "symbol", "marketSymbol", default=mint or "?"))

    @classmethod
    def parse_position(cls, p: dict) -> dict:
        """Normaliza una posición de la API a un dict chico y estable. Conserva `raw`."""
        size = _f(_first(p, "sizeUsd", "size", "positionSizeUsd", "sizeUsdDelta"))
        coll = _f(_first(p, "collateralUsd", "collateral", "collateralSizeUsd", "positionCollateralSizeUsd"))
        pnl = _f(_first(p, "pnlAfterFeesUsd", "pnlAfterFees", "pnlUsd", "pnl", "pnlBeforeFeesUsd"))
        pnl_pct = _f(_first(p, "pnlChangePctAfterFees", "pnlChangePctBeforeFees", "pnlPct", "pnlPercent"))
        lev = _f(_first(p, "leverage"))
        if lev is None and size and coll:
            lev = size / coll
        if pnl_pct is None and pnl is not None and coll:
            pnl_pct = 100.0 * pnl / coll
        side = str(_first(p, "side", "positionSide", default="?")).lower()
        ts = _first(p, "openTime", "openedAt", "createdTime", "createdAt", "openTimestamp", "updatedTime")
        opened_ts = None
        if ts is not None:
            opened_ts = _f(ts)
            if opened_ts and opened_ts > 1e12:   # vino en ms
                opened_ts = opened_ts / 1000.0
        return {
            "pubkey": _first(p, "positionPubkey", "pubkey", "publicKey", "address", "positionKey"),
            "symbol": cls._symbol_of(p),
            "side": side,
            "size_usd": size,
            "collateral_usd": coll,
            "entry": _f(_first(p, "entryPrice", "entryPriceUsd", "averagePrice", "avgPrice")),
            "mark": _f(_first(p, "markPrice", "markPriceUsd", "price", "indexPrice")),
            "liq_price": _f(_first(p, "liquidationPrice", "liquidationPriceUsd", "liqPrice")),
            "pnl_usd": pnl,
            "pnl_pct": pnl_pct,
            "leverage": lev,
            "opened_ts": opened_ts,
            "collateral_mint": _first(p, "collateralMint", "collateralTokenMint"),
            "market_mint": _first(p, "marketMint", "market", "mint"),
            "raw": p,
        }

    def positions(self) -> list[dict]:
        out = []
        for p in self.positions_raw():
            try:
                out.append(self.parse_position(p))
            except Exception as e:  # noqa: BLE001 — nunca tirar toda la lista por una posición rara
                self.log.warning("perps: cannot parse position %s: %s", json.dumps(p)[:300], e)
                out.append({"pubkey": None, "symbol": "?", "side": "?", "raw": p, "parse_error": str(e)})
        return out

    # -------------------------------------------------------------- saldos
    def usdc_balance(self) -> float:
        raw, dec = self.rpc.token_balance(self.wallet, USDC)
        return raw / (10 ** dec)

    def _check_collateral(self, collateral_usdc: float) -> None:
        bal = self.usdc_balance()
        if bal + 1e-9 < collateral_usdc:
            raise PerpsError(f"insufficient USDC collateral: have {bal:.4f}, need {collateral_usdc:.4f} (wallet {self.wallet})")
        sol = self.rpc.sol_balance(self.wallet)
        if sol < MIN_SOL_FOR_FEES:
            self.log.warning("perps: low SOL for fees/rent: %.5f SOL (< %.3f)", sol, MIN_SOL_FOR_FEES)

    # ----------------------------------------------------------- cotización
    @staticmethod
    def _validate(side: str, collateral_usdc: float, leverage: float) -> tuple[str, int]:
        side = side.lower()
        if side not in ("long", "short"):
            raise PerpsError(f"side must be 'long' or 'short', got {side!r}")
        if collateral_usdc <= 0:
            raise PerpsError("collateral_usdc must be > 0")
        if leverage < 1.0 or leverage > MAX_LEVERAGE:
            raise PerpsError(f"leverage {leverage} out of bounds [1, {MAX_LEVERAGE}]")
        return side, int(round(collateral_usdc * 10 ** USDC_DECIMALS))

    def _increase_body(self, symbol: str, side: str, collateral_raw: int, leverage: float, slippage_bps: int,
                       include_tx: bool, transaction_type: str | None) -> dict:
        mint = self._mint(symbol)
        lev = f"{leverage:g}"
        body = {
            "walletAddress": self.wallet,
            "marketMint": mint,
            "inputMint": USDC,                                   # siempre pagamos con USDC
            "collateralMint": USDC if side == "short" else mint,  # short → USDC; long → el token
            "side": side,
            "leverage": lev,
            "maxSlippageBps": str(int(slippage_bps)),
            "collateralTokenDelta": str(collateral_raw),
            "includeSerializedTx": bool(include_tx),
            "tpsl": [],
        }
        if transaction_type:
            body["transactionType"] = transaction_type
        return body

    def quote_open(self, symbol: str, side: str, collateral_usdc: float, leverage: float, slippage_bps: int = 100) -> dict:
        """Sólo cotización (sin tx). Devuelve el `quote` de la API más algunos campos útiles."""
        side, raw = self._validate(side, collateral_usdc, leverage)
        body = self._increase_body(symbol, side, raw, leverage, slippage_bps, include_tx=False, transaction_type=None)
        d = self._post("positions/increase", body) or {}
        q = d.get("quote") or d
        return {"symbol": symbol.upper(), "side": side, "collateral_usdc": collateral_usdc, "leverage": leverage,
                "quote": q, "position_pubkey": d.get("positionPubkey"), "raw": d}

    # ----------------------------------------------------------------- firma
    def _sign_preserving(self, serialized_b64: str) -> tuple[str, dict]:
        """Firma nuestro slot de una VersionedTransaction (legacy o v0) preservando las firmas
        ya presentes (p. ej. la del keeper). Devuelve (tx_b64_firmada, info).

        info: {"num_required": n, "signers": [pubkeys], "ours_index": i|None, "missing": [pubkeys sin firma]}
        """
        from solders.message import to_bytes_versioned
        from solders.signature import Signature
        from solders.transaction import VersionedTransaction

        tx = VersionedTransaction.from_bytes(base64.b64decode(serialized_b64))
        msg = tx.message
        n_req = msg.header.num_required_signatures
        keys = [str(k) for k in list(msg.account_keys)[:n_req]]
        sigs = list(tx.signatures)
        # la lista de firmas puede venir más corta que num_required (tx "sin firmar"); la completamos
        while len(sigs) < n_req:
            sigs.append(Signature.default())
        sigs = sigs[:n_req]

        ours = None
        for i, k in enumerate(keys):
            if k == self.wallet:
                ours = i
                sigs[i] = self.kp.sign_message(to_bytes_versioned(msg))
        if ours is None:
            raise PerpsError(f"our wallet {self.wallet} is not a required signer of this tx (signers: {keys})")

        missing = [keys[i] for i, s in enumerate(sigs) if bytes(s) == _EMPTY_SIG]
        signed = VersionedTransaction.populate(msg, sigs)
        info = {"num_required": n_req, "signers": keys, "ours_index": ours, "missing": missing}
        return base64.b64encode(bytes(signed)).decode(), info

    def _submit(self, serialized_b64: str, require_keeper: bool, timeout: float = CONFIRM_TIMEOUT_S) -> str:
        """Firma, manda por RPC y espera confirmación. Devuelve la firma o levanta con el error del RPC."""
        signed, info = self._sign_preserving(serialized_b64)
        self.log.info("perps submit: required=%d ours_index=%s missing=%s require_keeper=%s",
                      info["num_required"], info["ours_index"], info["missing"], require_keeper)
        if info["missing"]:
            # Puede fallar: lo intentamos igual (el keeper puede firmar después / la API puede haber prefirmado)
            self.log.warning("perps submit: sending with %d empty signature slot(s): %s", len(info["missing"]), info["missing"])
        try:
            sig = self.rpc.send_raw(signed)
        except Exception as e:  # noqa: BLE001
            raise PerpsError(f"sendTransaction rejected (missing={info['missing']}): {e}") from e
        self.log.info("perps submit: sent %s, waiting up to %.0fs", sig, timeout)
        st = self.rpc.wait_confirmed(sig, timeout=timeout)   # levanta RuntimeError si falló en cadena
        if not st:
            raise PerpsError(f"no confirmation for {sig} within {timeout:.0f}s")
        self.log.info("perps submit: confirmed %s (%s)", sig, st.get("confirmationStatus"))
        return sig

    @staticmethod
    def _is_sig_error(msg: str) -> bool:
        m = msg.lower()
        return "signature verification" in m or "missing signature" in m or "not enough signers" in m \
            or "signaturefailure" in m or "sanitize" in m

    # ------------------------------------------------------------- abrir
    def open(self, symbol: str, side: str, collateral_usdc: float, leverage: float,
             slippage_bps: int = 100, dry: bool = False) -> dict:
        """Abre una posición. Devuelve {ok, sig, position_pubkey, quote, error, path_used, attempts}.

        Caminos, en orden: transactionType 'legacy' → 'instant' (default de la API). Sólo pasamos al
        siguiente si la API rechazó el pedido o el RPC rechazó la tx *antes* de entrar; si la tx entró
        y no confirmó, NO reintentamos (podría duplicar la posición).
        """
        res = {"ok": False, "sig": None, "position_pubkey": None, "quote": None, "error": None,
               "path_used": None, "attempts": []}
        try:
            side, raw = self._validate(side, collateral_usdc, leverage)
            if not dry:
                self._check_collateral(collateral_usdc)
        except PerpsError as e:
            res["error"] = str(e)
            return res

        for ttype in ("legacy", "instant"):
            att = {"path": ttype}
            res["attempts"].append(att)
            try:
                body = self._increase_body(symbol, side, raw, leverage, slippage_bps, include_tx=True, transaction_type=ttype)
                d = self._post("positions/increase", body) or {}
            except PerpsApiError as e:
                att["api_error"] = e.body[:500]
                self.log.warning("perps open[%s]: API %d: %s", ttype, e.status, e.body[:300])
                continue
            except PerpsError as e:
                att["api_error"] = str(e)
                continue

            res["quote"] = d.get("quote")
            res["position_pubkey"] = d.get("positionPubkey")
            att.update({"transaction_type": d.get("transactionType"), "require_keeper": d.get("requireKeeperSignature"),
                        "position_request": d.get("positionRequestPubkey"), "tx_metadata": d.get("txMetadata")})
            tx_b64 = d.get("serializedTxBase64") or d.get("serializedTx") or d.get("transaction")
            if not tx_b64:
                att["error"] = f"no serialized tx in response: {json.dumps(d)[:300]}"
                continue
            q = d.get("quote") or {}
            if q.get("collateralLessThanFees"):
                res["error"] = f"collateral less than fees (openFeeUsd={q.get('openFeeUsd')})"
                res["path_used"] = ttype
                return res
            if dry:
                try:
                    _, info = self._sign_preserving(tx_b64)
                    att["sign_info"] = info
                except Exception as e:  # noqa: BLE001
                    att["sign_info"] = {"error": str(e)}
                res.update(ok=True, path_used=ttype, error="dry run: not sent")
                return res
            try:
                sig = self._submit(tx_b64, bool(d.get("requireKeeperSignature")))
            except PerpsError as e:
                att["error"] = str(e)
                self.log.error("perps open[%s]: %s", ttype, e)
                if str(e).startswith("sendTransaction rejected") and self._is_sig_error(str(e)):
                    continue       # no entró en cadena: probamos el otro camino
                res.update(error=str(e), path_used=ttype)
                return res
            except RuntimeError as e:  # falló en cadena (wait_confirmed) → no reintentar
                att["error"] = str(e)
                res.update(error=str(e), path_used=ttype)
                return res
            res.update(ok=True, sig=sig, path_used=ttype)
            res["position_seen"] = self._wait_position(res["position_pubkey"])
            return res

        res["error"] = "all paths failed: " + json.dumps(res["attempts"])[:800]
        return res

    def _wait_position(self, pubkey: str | None, timeout: float = 25) -> bool:
        """Tras confirmar, espera a que la posición aparezca en /positions (el keeper puede tardar)."""
        if not pubkey:
            return False
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if any(p.get("pubkey") == pubkey for p in self.positions()):
                    return True
            except Exception as e:  # noqa: BLE001
                self.log.debug("perps wait_position: %s", e)
            time.sleep(3)
        self.log.warning("perps: position %s not visible after %.0fs (keeper may still be fulfilling)", pubkey, timeout)
        return False

    # ------------------------------------------------------------- cerrar
    def close(self, position_pubkey: str, desired_mint: str = USDC, dry: bool = False) -> dict:
        """Cierra toda la posición. Primero /positions/decrease (legacy), fallback /positions-gasless/decrease."""
        res = {"ok": False, "sig": None, "position_pubkey": position_pubkey, "quote": None, "error": None,
               "path_used": None, "attempts": []}
        base = {"positionPubkey": position_pubkey, "desiredMint": desired_mint,
                "sizeUsdDelta": "0", "collateralUsdDelta": "0", "entirePosition": True}
        paths = [
            ("positions/decrease", {**base, "includeSerializedTx": True, "transactionType": "legacy"}),
            ("positions-gasless/decrease", dict(base)),
        ]
        for path, body in paths:
            att = {"path": path}
            res["attempts"].append(att)
            try:
                d = self._post(path, body) or {}
            except PerpsApiError as e:
                att["api_error"] = e.body[:500]
                self.log.warning("perps close[%s]: API %d: %s", path, e.status, e.body[:300])
                continue
            except PerpsError as e:
                att["api_error"] = str(e)
                continue
            res["quote"] = d.get("quote")
            att.update({"require_keeper": d.get("requireKeeperSignature"), "position_request": d.get("positionRequestPubkey"),
                        "transaction_type": d.get("transactionType")})
            tx_b64 = d.get("serializedTxBase64") or d.get("serializedTx") or d.get("transaction")
            if not tx_b64:
                att["error"] = f"no serialized tx in response: {json.dumps(d)[:300]}"
                continue
            if dry:
                try:
                    _, info = self._sign_preserving(tx_b64)
                    att["sign_info"] = info
                except Exception as e:  # noqa: BLE001
                    att["sign_info"] = {"error": str(e)}
                res.update(ok=True, path_used=path, error="dry run: not sent")
                return res
            try:
                sig = self._submit(tx_b64, bool(d.get("requireKeeperSignature")))
            except PerpsError as e:
                att["error"] = str(e)
                self.log.error("perps close[%s]: %s", path, e)
                if str(e).startswith("sendTransaction rejected"):
                    continue       # no entró: probamos el camino gasless
                res.update(error=str(e), path_used=path)
                return res
            except RuntimeError as e:
                att["error"] = str(e)
                res.update(error=str(e), path_used=path)
                return res
            res.update(ok=True, sig=sig, path_used=path)
            return res
        res["error"] = "all paths failed: " + json.dumps(res["attempts"])[:800]
        return res
