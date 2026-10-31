#!/bin/bash
# 31/10 18:20 — fábrica de marcas: ¿quiénes son las billeteras madre (9C4nRv… fondeó 34 creadores, 14 bombearon; 7Ud5vg… 4/4)?
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 500 python3 - <<'PY'
import json, os, requests, collections
from fomo_intel.desk.dd import funder_helius
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env
from fomo_intel.live.wallet import Rpc
rpc=Rpc(Env().rpc_url); HK=os.environ.get("HELIUS_API_KEY","")
toks=json.load(open("state/research/brand_factory.json"))
for M in ("9C4nRvhhVquCKATjDCx5FKvNS9PNgNqgyWy9AcoDjYv5","7Ud5vgBFoRNx9RSSNDDyk1ojawbXN2RcjiKDDajC6PAW","3dL83TFwgc7zzRvscDnLoK99sEVvU39f81VpdqWj4NtS"):
    g=[t for t in toks if t.get("f1")==M]
    d=next((t["dev"] for t in g),None)
    info=funder_helius(d) if d else None
    sigs=rpc.call("getSignaturesForAddress",[M,{"limit":1000}]) or []
    span=(sigs[0]["blockTime"]-sigs[-1]["blockTime"])/3600 if len(sigs)>1 and sigs[-1].get("blockTime") else None
    print(f"== {M}: identidad helius={info} · últimas {len(sigs)} tx en {span and round(span,1)} h · saldo {rpc.sol_balance(M):.2f} SOL")
    for t in sorted(g,key=lambda t:t["created"]):
        print(f"   {t['sym']!s:12} {t['name']!s:24.24} pico {t['peak']:>11,} c1 {t['c1']:>9,} estrato {t['s']}")
PY
