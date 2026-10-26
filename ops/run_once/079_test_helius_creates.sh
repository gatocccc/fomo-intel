#!/bin/bash
# Prueba 90 s: creaciones de pump.fun leídas directo de la cadena (Helius logsSubscribe al programa pump), volumen y cobertura vs PumpPortal.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 150 python3 - <<'PY'
import json, os, time, websocket
from fomo_intel.live.helius_watch import decode_create_from_logs
PUMP="6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
ws=websocket.create_connection(f"wss://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}",timeout=10)
ws.send(json.dumps({"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[{"mentions":[PUMP]},{"commitment":"processed"}]}))
t0=time.time(); n=0; nbytes=0; creates=[]; dec_fail=0
while time.time()-t0<90:
    try: raw=ws.recv()
    except Exception: continue
    nbytes+=len(raw); m=json.loads(raw)
    if m.get("method")!="logsNotification": print("msg",str(m)[:200]); continue
    n+=1; v=m["params"]["result"]["value"]
    if v.get("err"): continue
    lg=v.get("logs") or []
    if any("Instruction: Create" in l for l in lg):
        c=decode_create_from_logs(lg,"")
        if c: creates.append((time.time(),c["mint"]))
        else: dec_fail+=1
el=time.time()-t0
print(f"{el:.0f}s: {n} avisos ({n/el:.0f}/s), {nbytes/el/1e6:.2f} MB/s, creaciones {len(creates)} ({len(creates)/el*60:.0f}/min), creación sin decodificar {dec_fail}")
pp=[json.loads(l) for l in open("state/tweetshadow/creates.jsonl")][-400:]
ppm={r["mint"] for r in pp}
lo,hi=creates[0][0]-5,creates[-1][0]+5 if creates else (0,0)
pp_win=[r for r in pp if lo<=r["seen_ts"]<=hi]
print("PumpPortal en la misma ventana:",len(pp_win),"| de las de Helius también en PumpPortal:",sum(1 for _,m in creates if m in ppm))
print("finales de mint:",sorted({m[-4:] for _,m in creates})[:15])
PY
