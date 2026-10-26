#!/bin/bash
# 40 s: TradeEvents de pump.fun con discriminador (vs decodificador viejo), para medir volumen del 1er segundo en vivo.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 90 python3 - <<'PY'
import json, os, time, base64, struct, hashlib, websocket
from solders.pubkey import Pubkey
from fomo_intel.live.helius_watch import decode_trades_from_logs
D=hashlib.sha256(b"event:TradeEvent").digest()[:8]
ws=websocket.create_connection(f"wss://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}",timeout=10)
ws.send(json.dumps({"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[{"mentions":["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]},{"commitment":"processed"}]}))
t0=time.time(); n=old0=new=old=lens=0; samples=[]; disc=set(); sizes={}
while time.time()-t0<40:
    try: m=json.loads(ws.recv())
    except Exception: continue
    v=(m.get("params") or {}).get("result",{}).get("value",{})
    if not v or v.get("err"): continue
    lg=v.get("logs") or []
    for l in lg:
        if not l.startswith("Program data: "): continue
        b=base64.b64decode(l[14:]); disc.add(b[:8].hex()); sizes[b[:8].hex()]=len(b)
        if b[:8]==D:
            new+=1
            sol,tok=struct.unpack_from("<QQ",b,40)
            if len(samples)<4: samples.append((len(b),sol/1e9,tok/1e6,b[56],str(Pubkey.from_bytes(b[8:40]))[-6:]))
    for t in decode_trades_from_logs(lg):
        old+=1; old0+= t["sol"]==0
print("TradeEvent (discriminador):",new,"| decodificador viejo:",old,"con sol=0:",old0)
print("muestras (len, sol, tokens, is_buy, mint):",samples)
print("discriminadores vistos:",{k:sizes[k] for k in list(disc)[:12]}, "trade disc", D.hex())
PY
