#!/bin/bash
# (a) Toma de ganancia rápida sobre lanzamientos de fábricas (entrada realista = open*1.10). (b) Descubrir TODAS las fábricas activas
#     con los creadores vistos en vivo (state/creators.json) y su tasa de graduación real vía /deployer.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time, statistics as st
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
from fomo_intel.charts import ChartFetcher
res = json.load(open("state/ops/fabricas_sniper.json"))
cf = ChartFetcher(os.environ["SOLANATRACKER_API_KEY"], "data", sleep_s=0.0)
def sim_tp(c, entry_mult, tp, max_min, stop):
    entry = c[0]["o"] * entry_mult
    for i, x in enumerate(c[:max_min+1]):
        if i == 0:
            # en la vela de entrada solo cuenta lo que pasa después: usamos el high de la vela 0 con cautela (puede ser antes de nuestra entrada) -> ignorar
            continue
        if stop and x["l"] <= entry*(1-stop): return -stop
        if x["h"] >= entry*tp: return tp - 1
    last = c[min(max_min, len(c)-1)]["c"]
    return last/entry - 1
print("== (a) salida por toma de ganancia en <=3 min, entrada = open*1.10, por fábrica ==")
for dev, rows in res.items():
    # recargar velas (están en data/charts)
    out = {}
    for tp in (1.3, 1.5, 2.0):
        for stop in (None, 0.5):
            rets = []
            for r in rows:
                pass
            out[(tp, stop)] = None
    print(dev[:10], "(usar fase b para re-simular con velas cacheadas)")
# re-simular leyendo las velas guardadas por mint
import glob
by_dev_mints = {}
for dev in res:
    try:
        d = requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or []
    except Exception: continue
    mints = [t["mint"] for t in d if (t.get("createdAt") or 0) and now - t["createdAt"]/1000 > 3*3600]
    have = [m for m in mints if os.path.exists(f"data/charts/{m}.json")]
    by_dev_mints[dev] = have
    cs = [json.load(open(f"data/charts/{m}.json"))["candles"] for m in have]
    cs = [c for c in cs if len(c) >= 2 and c[0]["o"] > 0]
    line = f"{dev[:10]}… n={len(cs)} "
    for tp in (1.3, 1.5, 2.0):
        for stop in (None, 0.5):
            rets = [sim_tp(c, 1.10, tp, 3, stop) for c in cs]
            if rets: line += f"| TP{tp} stop{stop}: {sum(1 for r in rets if r>0)/len(rets):.0%} {sum(rets)/len(rets):+.2f} "
    print(line)
print("\n== (b) fábricas activas vistas en vivo (creators.json) ==")
cr = json.load(open("state/creators.json"))
busy = sorted(((len(v), k) for k, v in cr.items() if len(v) >= 8), reverse=True)
print("creadores con >=8 lanzamientos en 24 h vistos en vivo:", len(busy))
found = []
for n, dev in busy[:45]:
    try:
        d = requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json(); toks = d.get("data") or []
    except Exception as e: continue
    if not toks: continue
    grads = sum(1 for t in toks if (t.get("market") or "").lower() not in ("pumpfun", "pumpfun-curve", "pump", ""))
    mc = st.median([t.get("marketCapUsd") or 0 for t in toks])
    rate = grads/len(toks)
    found.append({"dev": dev, "vistos24h": n, "total_api": d.get("total"), "n": len(toks), "grads": grads, "rate": round(rate, 3), "mcap_med": round(mc)})
    print(f"  {dev[:10]}… 24h={n:3d} total={d.get('total'):6} grad {grads}/{len(toks)} = {rate:.1%} mcap_med {mc:,.0f}")
json.dump(found, open("state/ops/fabricas_vivas.json", "w"), indent=1)
PY
