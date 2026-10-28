#!/bin/bash
# Genera el par de claves de API de Turnkey (P-256) en el servidor. La privada no sale de secrets/; se imprime solo la pública.
cd /root/fomo_intel
python3 - <<'PY'
import json, os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
p = Path("secrets/turnkey_api.json")
if not p.exists():
    k = ec.generate_private_key(ec.SECP256R1())
    priv = format(k.private_numbers().private_value, "064x")
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint).hex()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f: json.dump({"public": pub, "private": priv}, f)
d = json.load(open(p))
json.dump({"public": d["public"]}, open("state/turnkey_pub.json", "w"))
print("PUBLICA", d["public"])
PY
