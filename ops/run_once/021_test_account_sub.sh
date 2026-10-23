#!/bin/bash
# Prueba directa: ¿PumpPortal entrega los trades de una cuenta muy activa (21gEdEoq..., opera en PumpSwap cada pocos minutos)?
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 240 python3 - <<'PY'
import json, os, time, websocket
key = os.environ["PUMPPORTAL_API_KEY"]
ws = websocket.create_connection(f"wss://pumpportal.fun/api/data?api-key={key}", timeout=30)
ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": ["21gEdEoqCh1YXXb5fviqQRtZRpPaDtGrHGsmDoib9eak", "13mWvbz8wc1JvLFuvBHfpmhuQ29DRtsKkznXbnPuSdUm", "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK"]}))
t0 = time.time(); n = 0
while time.time() - t0 < 200:
    try:
        m = ws.recv()
    except websocket.WebSocketTimeoutException:
        print("…sin mensajes 30 s"); continue
    n += 1
    print(round(time.time() - t0), m[:400])
    if n > 40: break
print("total mensajes:", n)
PY
