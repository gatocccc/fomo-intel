#!/bin/bash
# Tasa de financiamiento real de Hyperliquid (90 días): ¿cuánto rinde cobrar funding con cobertura (spot largo + perp corto)?
cd /root/fomo_intel
timeout 580 python3 -u - <<'PY'
import requests, time, statistics as st, json
U = "https://api.hyperliquid.xyz/info"
now = int(time.time()*1000); start = now - 90*86400*1000
meta = requests.post(U, json={"type": "metaAndAssetCtxs"}, timeout=30).json()
univ = meta[0]["universe"]; ctx = meta[1]
assets = []
for a, c in zip(univ, ctx):
    oi = float(c.get("openInterest") or 0) * float(c.get("markPx") or 0); vol = float(c.get("dayNtlVlm") or 0)
    if a.get("isDelisted"): continue
    assets.append((a["name"], oi, vol, float(c.get("funding") or 0)))
assets.sort(key=lambda x: -x[2])
top = [a for a in assets if a[2] > 20_000_000][:40]
print("activos con volumen diario > US$20M:", len(top))
res = {}
for name, oi, vol, f_now in top:
    rows = []; t = start
    while t < now:
        r = requests.post(U, json={"type": "fundingHistory", "coin": name, "startTime": t, "endTime": now}, timeout=30).json()
        if not r: break
        rows += r; t = r[-1]["time"] + 1
        if len(r) < 500: break
    if not rows: continue
    f = [float(x["fundingRate"]) for x in rows]          # por hora
    res[name] = {"n": len(f), "apr": sum(f)/len(f)*24*365*100, "pos": sum(1 for x in f if x > 0)/len(f), "oi": oi, "vol": vol, "f": f, "times": [x["time"] for x in rows]}
print("\n%-8s %8s %8s %10s %12s" % ("activo", "horas", "APR %", "% horas+", "OI US$M"))
for k, v in sorted(res.items(), key=lambda kv: -kv[1]["apr"]):
    print("%-8s %8d %8.1f %9.0f%% %12.0f" % (k, v["n"], v["apr"], v["pos"]*100, v["oi"]/1e6))
# Estrategia simple sin mirar el futuro: cada 7 días, elegir los 5 activos con mayor funding promedio de los 7 días PREVIOS (si es positivo) y cobrar su funding los 7 días siguientes.
# Costos: 0,1% por rotación (entrada+salida de spot y perp aprox, 4 patas) cada vez que cambia un activo.
H = 24*7
L = min(len(v["f"]) for v in res.values())
names = [k for k in res if len(res[k]["f"]) >= L]
weekly = []; prev = set()
for w in range(1, L // H):
    a, b = (w-1)*H, w*H
    score = sorted(((sum(res[k]["f"][a:b]), k) for k in names), reverse=True)
    pick = [k for s, k in score[:5] if s > 0]
    if not pick: weekly.append(0.0); prev = set(); continue
    nxt = [sum(res[k]["f"][b:b+H]) for k in pick]
    gross = sum(nxt)/len(pick)
    changed = len(set(pick) ^ prev) / max(1, len(pick)) / 2
    weekly.append(gross - 0.001 * changed - 0.0002)   # costos de rotación + mantenimiento
    prev = set(pick)
tot = 1.0
for r in weekly: tot *= (1 + r)
print(f"\nrotación semanal top-5 (sin mirar el futuro): {len(weekly)} semanas, ganadas {sum(1 for r in weekly if r>0)}/{len(weekly)}, semana mediana {st.median(weekly)*100:+.2f}%, peor {min(weekly)*100:+.2f}%")
print(f"resultado acumulado {(tot-1)*100:+.1f}% en {len(weekly)} semanas ≈ {((tot)**(52/len(weekly))-1)*100:+.0f}% anual (sin apalancamiento, neto de costos estimados)")
btc = res.get("BTC"); eth = res.get("ETH")
for k in ("BTC", "ETH", "SOL", "HYPE"):
    if k in res: print(f"solo {k}: APR {res[k]['apr']:.1f}%  horas positivas {res[k]['pos']*100:.0f}%")
PY
