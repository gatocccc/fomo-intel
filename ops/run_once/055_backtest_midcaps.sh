#!/bin/bash
# Prueba con método corregido sobre memecoins con liquidez real (velas 1 h, ~90 días):
# entrada al OPEN de la vela SIGUIENTE a la señal, costo 1% por lado, mitad de datos reservada (fuera de muestra), comparación contra azar.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 590 python3 -u - <<'PY'
import json, os, requests, time, random, statistics as st
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = int(time.time())
known = {"BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
 "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "MEW": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5", "BOME": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",
 "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "GOAT": "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump", "PNUT": "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump",
 "MOODENG": "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY", "CHILLGUY": "Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump", "AI16Z": "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",
 "GIGA": "63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9", "RETARDIO": "6ogzHhzdrQr9Pgv6hZ2MNze7UrzBMAFyBBWUYp1Fhitx", "MICHI": "5mbK36SZ7J19An8jFochhQS4of8g6BwUjbeCSxBSoWdp",
 "PONKE": "5z3EqYQo9HiCEs3R84RCDMu2n7anpDMxRhdK8PSWmrRC"}
uni = {t["sym"]: t["mint"] for t in json.load(open("state/ops/universo_midcaps.json"))
       if t["sym"] not in ("cbBTC", "ETH", "WBTC", "EURC", "ZEC", "NEAR", "XMR", "NVDAx", "HYPE", "KMNO", "ORE", "ENA", "GEOD")}
uni.update(known)
series = {}
for sym, mint in uni.items():
    try:
        r = requests.get(f"{B}/chart/{mint}", headers=h, params={"type": "1h", "time_from": now - 90*86400, "time_to": now}, timeout=40)
        cs = r.json().get("oclhv") or []
    except Exception as e: print(sym, "error", e); continue
    cs = [{"t": int(c["time"]/1000) if c["time"] > 1e11 else int(c["time"]), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"], "v": c.get("volume", 0)} for c in cs if c.get("open")]
    cs.sort(key=lambda c: c["t"])
    if len(cs) < 24*30: print(f"  {sym}: {len(cs)} velas (descartado)"); continue
    series[sym] = cs
print("tokens con >=30 días de velas 1h:", len(series), sorted(series))
COST = 0.01
def run(cs, sig, exit_rule, i0, i1):
    trades = []; i = max(i0, 60)
    while i < min(i1, len(cs) - 2):
        if sig(cs, i):
            e = cs[i+1]["o"] * (1 + COST); j = i + 1; peak = e; out = None
            while j < len(cs) - 1:
                c = cs[j]; peak = max(peak, c["h"])
                px, why = exit_rule(cs, j, e, peak, j - (i+1))
                if px: out = (px * (1 - COST), j, why); break
                j += 1
            if not out: out = (cs[-1]["c"] * (1 - COST), len(cs) - 1, "fin")
            trades.append(out[0]/e - 1); i = out[1] + 1
        else: i += 1
    return trades
def mx(cs, i, n, k="h"): return max(c[k] for c in cs[i-n:i])
def mn(cs, i, n, k="l"): return min(c[k] for c in cs[i-n:i])
def ma(cs, i, n): return sum(c["c"] for c in cs[i-n:i]) / n
S = {
 "ruptura 48h + trailing 15%": (lambda cs, i: cs[i]["c"] > mx(cs, i, 48), lambda cs, j, e, pk, k: ((pk*0.85, "trail") if cs[j]["l"] <= pk*0.85 else ((cs[j]["c"], "tiempo") if k >= 168 else (None, None)))),
 "ruptura 48h + TP10/SL10": (lambda cs, i: cs[i]["c"] > mx(cs, i, 48), lambda cs, j, e, pk, k: ((e*0.9, "sl") if cs[j]["l"] <= e*0.9 else ((e*1.1, "tp") if cs[j]["h"] >= e*1.1 else ((cs[j]["c"], "t") if k >= 72 else (None, None))))),
 "caída 20% en 24h, rebote TP8/SL15": (lambda cs, i: cs[i]["c"] < cs[i-24]["c"]*0.8, lambda cs, j, e, pk, k: ((e*0.85, "sl") if cs[j]["l"] <= e*0.85 else ((e*1.08, "tp") if cs[j]["h"] >= e*1.08 else ((cs[j]["c"], "t") if k >= 72 else (None, None))))),
 "caída 20% en 24h sobre MA 30d, TP8/SL15": (lambda cs, i: cs[i]["c"] < cs[i-24]["c"]*0.8 and ma(cs, i, 60) > 0 and cs[i]["c"] > mn(cs, i, 60, "c"), lambda cs, j, e, pk, k: ((e*0.85, "sl") if cs[j]["l"] <= e*0.85 else ((e*1.08, "tp") if cs[j]["h"] >= e*1.08 else ((cs[j]["c"], "t") if k >= 72 else (None, None))))),
 "tendencia MA20>MA50 (cruce), sale al cruce": (lambda cs, i: ma(cs, i, 20) > ma(cs, i, 50) and ma(cs, i-1, 20) <= ma(cs, i-1, 50), lambda cs, j, e, pk, k: ((cs[j]["c"], "cruce") if j >= 50 and ma(cs, j, 20) < ma(cs, j, 50) else (None, None))),
 "volumen 3x + vela verde, TP10/SL8 24h": (lambda cs, i: cs[i]["v"] > 3*sum(c["v"] for c in cs[i-24:i])/24 and cs[i]["c"] > cs[i]["o"]*1.03, lambda cs, j, e, pk, k: ((e*0.92, "sl") if cs[j]["l"] <= e*0.92 else ((e*1.1, "tp") if cs[j]["h"] >= e*1.1 else ((cs[j]["c"], "t") if k >= 24 else (None, None))))),
}
random.seed(7)
S["AZAR (control) TP8/SL15"] = (lambda cs, i: random.random() < 0.01, S["caída 20% en 24h, rebote TP8/SL15"][1])
print("\n%-44s | %-34s | %-34s" % ("estrategia", "1ª mitad (diseño)", "2ª mitad (prueba)"))
for name, (sig, ex) in S.items():
    res = []
    for half in (0, 1):
        tr = []
        for sym, cs in series.items():
            mid = len(cs)//2
            tr += run(cs, sig, ex, 0 if half == 0 else mid, mid if half == 0 else len(cs))
        if tr: res.append(f"n={len(tr):4d} acierto {sum(1 for x in tr if x>0)/len(tr):4.0%} prom {sum(tr)/len(tr):+.3f} med {st.median(tr):+.3f}")
        else: res.append("sin operaciones")
    print("%-44s | %-34s | %-34s" % (name, res[0], res[1]))
bh = [cs[-1]["c"]/cs[len(cs)//2]["o"] - 1 for cs in series.values()]
print(f"\ncomprar y mantener la 2ª mitad: mediana {st.median(bh):+.2f}, promedio {sum(bh)/len(bh):+.2f} (contexto del mercado en el período de prueba)")
PY
