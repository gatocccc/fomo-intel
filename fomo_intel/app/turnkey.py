"""Cliente mínimo de Turnkey (API firmada con la clave P-256 del servidor, secrets/turnkey_api.json)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

API = "https://api.turnkey.com"
KEY_FILE = Path(os.getenv("TURNKEY_KEY_FILE", "secrets/turnkey_api.json"))


def _key():
    d = json.load(open(KEY_FILE))
    return d["public"], ec.derive_private_key(int(d["private"], 16), ec.SECP256R1())


def call(path: str, body: dict, timeout: float = 20) -> dict:
    pub, priv = _key()
    payload = json.dumps(body, separators=(",", ":"))
    sig = priv.sign(payload.encode(), ec.ECDSA(hashes.SHA256())).hex()
    stamp = base64.urlsafe_b64encode(json.dumps({"publicKey": pub, "scheme": "SIGNATURE_SCHEME_TK_API_P256", "signature": sig}).encode()).decode().rstrip("=")
    r = requests.post(API + path, data=payload, headers={"Content-Type": "application/json", "X-Stamp": stamp}, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"turnkey {path} {r.status_code}: {r.text[:300]}")
    return r.json()


def org() -> str:
    return os.environ["TURNKEY_ORG_ID"]


def whoami() -> dict:
    return call("/public/v1/query/whoami", {"organizationId": org()})


if __name__ == "__main__":
    print(json.dumps(whoami(), indent=1))
