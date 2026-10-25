#!/bin/bash
# ¿Cuál es la mejor salida en lanzamientos de fábricas? TP rápido vs aguantar a graduación vs mixtas. Velas de 1 h (y 6 h si hay).
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time, statistics as st
from fomo_intel.charts import ChartFetcher
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
cf = ChartFetcher(os.environ["SOLANATRACKER_API_KEY"], "data", sleep_s=0.0)
facs = json.load(open("state/factories.json"))["wallets"]
BASE = 30.0/1_073_000_000.0
toks_all = []
for dev in facs:
    d = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    d = [t for t in d if (t.get("createdAt") or 0) and now - t["createdAt"]/1000 > 7*3600]
    for t in d[:80]:
        mint = t["mint"]; created = int(t["createdAt"]/1000)
        try: c = cf.fetch(mint, created, hours=6.0, force=not os.path.exists(f"data/charts/{mint}.json") or json.load(open(f"data/charts/{mint}.json")).get("hours", 0) < 6)
        except Exception: continue
        if len(c) < 2 or c[0]["o"] <= 0: continue
        grad = (t.get("market") or "").lower() not in ("pumpfun", "pumpfun-curve", "pump", "")
        toks_all.append({"dev": dev[:6], "c": c, "grad": grad, "sym": t.get("symbol")})
print("tokens de fábricas con velas 6 h:", len(toks_all), "| graduados:", sum(x["grad"] for x in toks_all), f"({sum(x['grad'] for x in toks_all)/len(toks_all):.0%})")
# múltiplo de graduación respecto del precio base de la curva (85 SOL reales -> vSol 115): (115/30)^2 ≈ 14.7x
def sim(c, legs, stop=0.5, max_min=360, entry_mult=1.10):
    """legs: lista de (multiplo, fraccion). El resto se vende a max_min o en stop. Entrada = open vela 0 * entry_mult."""
    entry = c[0]["o"] * entry_mult; rem = 1.0; cash = 0.0; done = [False]*len(legs)
    for i, x in enumerate(c[1:max_min+1], 1):
        if x["l"] <= entry*(1-stop):
            cash += rem * min(entry*(1-stop), x["c"]) / entry; rem = 0; break
        for k, (m, f) in enumerate(legs):
            if not done[k] and x["h"] >= entry*m:
                done[k] = True; q = min(f, rem); cash += q*m; rem -= q
        if rem <= 1e-9: break
    if rem > 0:
        last = c[min(max_min, len(c)-1)]["c"]; cash += rem*last/entry
    return cash*0.98 - 1    # 2% de fees/slippage de salida
entry_vs_base = [x["c"][0]["o"]*1.1/BASE for x in toks_all]
print(f"entrada estimada vs precio base de la curva: mediana {st.median(entry_vs_base):.2f}x  -> graduar ≈ {14.7/st.median(entry_vs_base):.1f}x desde nuestra entrada")
G = 14.7
plans = {
  "TP 1.5x todo (actual), 3 min": ([(1.5, 1.0)], 0.5, 3),
  "TP 2x todo, 10 min": ([(2.0, 1.0)], 0.5, 10),
  "TP 3x todo, 30 min": ([(3.0, 1.0)], 0.5, 30),
  "aguantar a graduación (todo), 6 h": ([(G/1.3, 1.0)], 0.6, 360),
  "aguantar a graduación sin stop, 6 h": ([(G/1.3, 1.0)], 0.99, 360),
  "50% a 1.5x + 50% a graduación": ([(1.5, 0.5), (G/1.3, 0.5)], 0.5, 360),
  "50% a 2x + 50% a graduación": ([(2.0, 0.5), (G/1.3, 0.5)], 0.5, 360),
  "70% a 1.5x + 30% a graduación": ([(1.5, 0.7), (G/1.3, 0.3)], 0.5, 360),
  "1/3 a 1.5x, 1/3 a 3x, 1/3 a graduación": ([(1.5, 0.34), (3.0, 0.33), (G/1.3, 0.33)], 0.5, 360),
}
by_dev = {}
for x in toks_all: by_dev.setdefault(x["dev"], []).append(x)
print("\n%-42s %6s %8s %8s %8s %8s" % ("plan", "n", "acierto", "ret/op", "mediana", "peor"))
for name, (legs, stop, mx) in plans.items():
    r = [sim(x["c"], legs, stop, mx) for x in toks_all]
    print("%-42s %6d %7.0f%% %+8.2f %+8.2f %+8.2f" % (name, len(r), 100*sum(1 for z in r if z > 0)/len(r), sum(r)/len(r), st.median(r), min(r)))
print("\npor fábrica (acierto / ret por op):")
for dev, xs in by_dev.items():
    line = f"  {dev} n={len(xs):3d} grad={sum(x['grad'] for x in xs)/len(xs):.0%} |"
    for name in ("TP 1.5x todo (actual), 3 min", "aguantar a graduación (todo), 6 h", "50% a 1.5x + 50% a graduación", "1/3 a 1.5x, 1/3 a 3x, 1/3 a graduación"):
        legs, stop, mx = plans[name]; r = [sim(x["c"], legs, stop, mx) for x in xs]
        line += f" {name[:14]}: {sum(1 for z in r if z>0)/len(r):.0%} {sum(r)/len(r):+.2f} |"
    print(line)
# de los graduados: cuánto tardaron y cuánto cae el precio antes de graduar (riesgo de stop)
gt = []
for x in toks_all:
    if not x["grad"]: continue
    entry = x["c"][0]["o"]*1.1
    i = next((i for i, k in enumerate(x["c"]) if k["h"] >= entry*G/1.3), None)
    dd = min(k["l"] for k in x["c"][:i+1])/entry if i else None
    gt.append((i, dd))
gt2 = [g for g in gt if g[0] is not None]
if gt2: print(f"\ngraduados que tocan el precio de graduación en las velas: {len(gt2)}/{len(gt)} ; minutos mediana {st.median(g[0] for g in gt2)} ; peor caída previa mediana {st.median(g[1] for g in gt2):.2f}x")
print("requests:", cf.requests_made)
PY
