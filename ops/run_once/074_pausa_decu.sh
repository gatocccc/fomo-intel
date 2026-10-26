#!/bin/bash
# Pausa de compras de la copia de decu (26/10 10:50 ART). Primera hora real: 6 intentos, 0 compras.
# decu compra 2 SOL en tokens de ~40-70 SOL de mcap: su propia compra + el enjambre suben el precio 28-80% antes de que lleguemos (0,9 s).
# Con el precio que nos cotizaban, 5 de 6 copias hubieran perdido (prom. ~-14%). No se toca nada más: el bot sigue escuchando y registrando.
cd /root/fomo_intel
python3 - <<'PY'
import json
p = "state/control.json"; d = json.load(open(p))
d["trading_enabled"] = False
json.dump(d, open(p, "w"), indent=1)
print("trading_enabled:", d["trading_enabled"], "| mode:", d["mode"], "| strategy:", d["strategy"])
PY
python3 -c "import json;print('abiertas:', len(json.load(open('state/positions.json'))) if __import__('os').path.exists('state/positions.json') else 0)"
