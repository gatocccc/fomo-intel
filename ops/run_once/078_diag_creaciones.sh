#!/bin/bash
# ¿Por qué la sombra (PumpPortal) no ve 14 de 16 tokens que compró decu? Cómo se crearon (programa, instrucción, versión de tx).
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 500 python3 - <<'PY'
import json, os, requests, time
from collections import Counter
RPC=f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
def rpc(m,p):
    for i in range(4):
        try:
            j=requests.post(RPC,json={"jsonrpc":"2.0","id":1,"method":m,"params":p},timeout=30).json()
            if "error" not in j: return j["result"]
        except Exception: pass
        time.sleep(1)
rows=[json.loads(l) for l in open("state/tweetshadow/creates.jsonl")]
seen={r["mint"] for r in rows}; t0=min(r["seen_ts"] for r in rows)
sig=[json.loads(l) for l in open("state/signals.jsonl") if l.strip()]
first={}
for s in sig:
    if s["ts"]>=t0 and (s.get("sol") or 0)>=1: first.setdefault(s["mint"],s)
progs=Counter()
for m,s in list(first.items()):
    sigs=[]; before=None
    for _ in range(5):
        pg=rpc("getSignaturesForAddress",[m,{"limit":1000,**({"before":before} if before else {})}]) or []
        sigs+=pg
        if len(pg)<1000: break
        before=pg[-1]["signature"]
    if not sigs: print(m,"sin firmas"); continue
    c=sigs[-1]; tx=rpc("getTransaction",[c["signature"],{"encoding":"jsonParsed","maxSupportedTransactionVersion":1}]) or {}
    logs=(tx.get("meta") or {}).get("logMessages") or []
    inst=[l.split("Instruction: ")[1] for l in logs if "Instruction: " in l][:6]
    p1=[l.split()[1][:12] for l in logs if l.startswith("Program ") and " invoke [1]" in l]
    ver=tx.get("version"); pump=any("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P" in l for l in logs)
    progs[(ver,pump)]+=1
    print(f"{m[:10]} {'VISTO' if m in seen else 'no visto'} | fin={m[-4:]} | tx v{ver} | pump={pump} | prog1={p1[:3]} | inst={inst} | firmas>={len(sigs)} | decu {s['sol']:.2f} SOL")
print("versión/pump:",progs)
PY
