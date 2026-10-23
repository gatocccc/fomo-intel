"""Billetera del bot: se genera en el servidor la primera vez y nunca sale de ahí.

Archivo (permisos 600): {"pubkey": "...", "secret_b58": "..."}  (clave completa de 64 bytes en base58,
el mismo formato que importan Phantom/Solflare si algún día hay que recuperarla a mano).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests


def load_or_create(path: Path) -> "Keypair":  # noqa: F821
    from solders.keypair import Keypair

    path = Path(path)
    if path.exists():
        d = json.load(open(path))
        return Keypair.from_base58_string(d["secret_b58"])
    kp = Keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"pubkey": str(kp.pubkey()), "secret_b58": str(kp), "created": int(time.time())}, f)
    return kp


class Rpc:
    def __init__(self, url: str):
        self.url = url

    def call(self, method: str, params: list, timeout: float = 20):
        r = requests.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"{method}: {d['error']}")
        return d.get("result")

    def sol_balance(self, pubkey: str) -> float:
        return (self.call("getBalance", [pubkey]) or {}).get("value", 0) / 1e9

    def token_balance(self, owner: str, mint: str) -> tuple[float, int]:
        """(cantidad en unidades enteras (raw), decimales)."""
        res = self.call("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}]) or {}
        raw, dec = 0, 6
        for acc in res.get("value", []):
            info = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
            raw += int(info["amount"]); dec = int(info["decimals"])
        return raw, dec

    def send_raw(self, raw_b64: str) -> str:
        return self.call("sendTransaction", [raw_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3,
                                                        "preflightCommitment": "processed"}])

    def wait_confirmed(self, sig: str, timeout: float = 60) -> dict | None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            res = self.call("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}]) or {}
            st = (res.get("value") or [None])[0]
            if st:
                if st.get("err"):
                    raise RuntimeError(f"tx falló en cadena: {st['err']}")
                if st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return st
            time.sleep(1.5)
        return None

    def fill_details(self, sig: str, owner: str, mint: str) -> dict:
        """SOL y tokens que realmente entraron/salieron de la billetera en esa tx."""
        tx = self.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}])
        if not tx:
            return {}
        meta = tx["meta"]; keys = tx["transaction"]["message"]["accountKeys"]
        idx = next((i for i, k in enumerate(keys) if (k.get("pubkey") if isinstance(k, dict) else k) == owner), 0)
        sol_delta = (meta["postBalances"][idx] - meta["preBalances"][idx]) / 1e9
        def tok(bals):
            return sum(float(b["uiTokenAmount"]["uiAmount"] or 0) for b in bals if b.get("owner") == owner and b.get("mint") == mint)
        tok_delta = tok(meta.get("postTokenBalances") or []) - tok(meta.get("preTokenBalances") or [])
        return {"sol_delta": sol_delta, "token_delta": tok_delta, "fee_sol": meta.get("fee", 0) / 1e9,
                "slot": tx.get("slot"), "block_time": tx.get("blockTime")}
