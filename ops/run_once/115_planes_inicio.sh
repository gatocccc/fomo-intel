#!/bin/bash
# Primeras posiciones de los planes: saldos, tendencia de 20 días (tradicional), candidatos y anti-rug (equilibrado y agresivo).
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "=== saldos"; for p in agresivo equilibrado tradicional; do python3 -c "import json;d=json.load(open('state/plan_${p}_summary.json'));print('$p', d.get('started', True), d.get('cash_sol'), d.get('start_usd'), d.get('equity_usd'))"; done
echo; echo "=== tradicional: precio vs promedio de 20 días (velas diarias)"
python3 - <<'PY'
import os, time, requests
H={"x-api-key":os.environ["SOLANATRACKER_API_KEY"]}; B="https://data.solanatracker.io"; now=int(time.time())
A={"SOL":"So11111111111111111111111111111111111111112","cbBTC":"cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij","WETH":"7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs","JUP":"JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}
for k,m in A.items():
    t=requests.get(f"{B}/tokens/{m}",headers=H,timeout=20).json(); tok=t.get("token",{}); pl=max(t.get("pools") or [{}],key=lambda q:(q.get("liquidity") or {}).get("usd") or 0)
    cs=(requests.get(f"{B}/chart/{m}",headers=H,params={"type":"1d","time_from":now-40*86400,"time_to":now},timeout=30).json() or {}).get("oclhv",[])
    cl=[float(c["close"]) for c in cs]
    if len(cl)<21: print(k,"velas insuficientes",len(cl)); continue
    ma20=sum(cl[-21:-1])/20; ma10=sum(cl[-11:-1])/10
    print(f"{k:6s} {tok.get('symbol')} {tok.get('name')} liq ${((pl.get('liquidity') or {}).get('usd') or 0)/1e6:.1f}M | precio {cl[-1]:.4f} ma20 {ma20:.4f} ({cl[-1]/ma20-1:+.1%}) ma10 {ma10:.4f} ({cl[-1]/ma10-1:+.1%}) | 7d {cl[-1]/cl[-8]-1:+.1%} 30d {cl[-1]/cl[-31]-1 if len(cl)>31 else 0:+.1%}")
PY
echo; echo "=== equilibrado: scan2 (mcap 3–500M, liq >= 500K)"
timeout 600 python3 -u -m fomo_intel.desk.scan2 > /tmp/scan2.txt 2>&1; head -3 /tmp/scan2.txt
python3 - <<'PY' > /tmp/eq_top.txt
import json
d=json.load(open("state/desk/scan2.json"))
c=[v for v in d["real"] if v["mcap"]>=3e6 and v["liq"]>=5e5 and (v.get("top10") or 0)<35 and v["ch24"]<1.0]
c.sort(key=lambda v:-(min(v["vol_mcap"],2)*(1.3 if 0.55<=v["from_hi"]<=0.92 else 1)*(1+max(min(v["ch72"] or 0,2),-0.4))))
for v in c[:8]: print(f"{v['sym']} mcap {v['mcap']/1e6:.1f}M liq {v['liq']/1e3:.0f}K vol/mcap {v['vol_mcap']:.0%} CV {v['cv']:.2f} 6h {v['ch6']:+.0%} 24h {v['ch24']:+.0%} 72h {(v['ch72'] or 0):+.0%} max7d {v['from_hi']:.0%} top10 {round(v.get('top10') or 0)}% {v['mint']} {v['tw'][:40]} {v['desc'][:50]}")
open("/tmp/eq_mints.txt","w").write(" ".join(v["mint"] for v in c[:4]))
PY
cat /tmp/eq_top.txt
echo "--- anti-rug top 4 equilibrado"; timeout 900 python3 -u -m fomo_intel.desk.dd $(cat /tmp/eq_mints.txt) | grep -v "^detalle"
echo; echo "=== agresivo: scan4 + anti-rug top 5"
timeout 600 python3 -u -m fomo_intel.desk.scan4 | tail -12
TOP=$(cat state/desk/scan4_top.txt 2>/dev/null); echo "top: $TOP"
[ -n "$TOP" ] && timeout 900 python3 -u -m fomo_intel.desk.dd $TOP | grep -v "^detalle"
