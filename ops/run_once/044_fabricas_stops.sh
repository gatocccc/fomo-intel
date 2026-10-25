#!/bin/bash
# ¿El stop corta tokens que después se recuperan? Sensibilidad stop x objetivo x tiempo en lanzamientos de fábricas (velas ya bajadas).
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time, statistics as st, itertools
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
facs = json.load(open("state/factories.json"))["wallets"]
toks = []
for dev in facs:
    d = (requests.get(f"{B}/deployer/{dev}", headers=h, timeout=30).json().get("data") or [])
    for t in d:
        p = f"data/charts/{t['mint']}.json"
        if (t.get("createdAt") or 0) and now - t["createdAt"]/1000 > 7*3600 and os.path.exists(p):
            c = json.load(open(p))["candles"]
            if len(c) >= 2 and c[0]["o"] > 0: toks.append({"dev": dev[:6], "c": c})
print("tokens:", len(toks))
def sim(c, tp, stop, mx, entry_mult=1.10):
    entry = c[0]["o"]*entry_mult
    for x in c[1:mx+1]:
        if stop < 0.99 and x["l"] <= entry*(1-stop): return (min(entry*(1-stop), x["c"])/entry)*0.98 - 1, "stop"
        if x["h"] >= entry*tp: return tp*0.98 - 1, "tp"
    return (c[min(mx, len(c)-1)]["c"]/entry)*0.98 - 1, "tiempo"
# 1) ¿cuántos de los que tocan -50% después llegan a 1.5x / 3x?
for thr in (0.5, 0.7):
    hit = rec15 = rec3 = 0
    for t in toks:
        c = t["c"]; entry = c[0]["o"]*1.10
        i = next((i for i, x in enumerate(c[1:61], 1) if x["l"] <= entry*(1-thr)), None)
        if i is None: continue
        hit += 1
        after = max((x["h"] for x in c[i+1:]), default=0)/entry
        rec15 += after >= 1.5; rec3 += after >= 3
    print(f"tocan -{int(thr*100)}% en la 1ª hora: {hit}/{len(toks)} ; de esos, después llegan a 1,5x: {rec15} ({rec15/max(1,hit):.0%}) ; a 3x: {rec3} ({rec3/max(1,hit):.0%})")
# 2) grilla
res = []
for tp, stop, mx in itertools.product((1.3, 1.5, 2.0, 3.0), (0.3, 0.5, 0.7, 0.99), (3, 10, 30, 120)):
    r = [sim(t["c"], tp, stop, mx) for t in toks]; v = [z[0] for z in r]
    res.append((tp, stop, mx, round(sum(1 for z in v if z > 0)/len(v), 2), round(sum(v)/len(v), 3), round(st.median(v), 2), sum(1 for z in r if z[1] == "stop")))
print("\n(tp, stop[0.99=sin stop], max_min, acierto, ret/op, mediana, n_stops) — top 12 por ret/op:")
for r in sorted(res, key=lambda r: -r[4])[:12]: print("  ", r)
print("top 12 por acierto con ret/op>0:")
for r in sorted([r for r in res if r[4] > 0], key=lambda r: (-r[3], -r[4]))[:12]: print("  ", r)
print("efecto del stop con TP1.5 y 3 / 10 / 30 min:")
for mx in (3, 10, 30):
    print("  ", mx, "min:", [(s, a, rr) for (tp, s, m, a, rr, md, ns) in res if tp == 1.5 and m == mx])
# 3) por fábrica, mejor combinación
for dev in sorted({t["dev"] for t in toks}):
    sub = [t for t in toks if t["dev"] == dev]; best = None
    for tp, stop, mx in itertools.product((1.3, 1.5, 2.0, 3.0), (0.3, 0.5, 0.7, 0.99), (3, 10, 30, 120)):
        v = [sim(t["c"], tp, stop, mx)[0] for t in sub]; a = sum(1 for z in v if z > 0)/len(v); e = sum(v)/len(v)
        if best is None or e > best[4]: best = (tp, stop, mx, round(a, 2), round(e, 3))
    print(f"  {dev} n={len(sub)} mejor (tp, stop, min, acierto, ret/op): {best}")
PY
