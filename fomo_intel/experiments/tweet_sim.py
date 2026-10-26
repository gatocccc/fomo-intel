"""Corte del modo sombra (Helius) vs compras de decu + simulación "entrar antes que él".
Para los tokens de tweet que compró decu y una muestra de los que NO compró: velas de 1 s de Solana Tracker desde la creación;
entrada al segundo ENTRY (cierre de esa vela + slippage), salida a los EXIT s (o stop/tp). Uso: python -m fomo_intel.experiments.tweet_sim
"""
import json, os, random, time, requests
from collections import Counter
ST = "https://data.solanatracker.io"; H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
rows = [json.loads(l) for l in open("state/tweetshadow/creates_helius.jsonl")]
by = {r["mint"]: r for r in rows}; t0 = min(r["seen_ts"] for r in rows)
sig = [json.loads(l) for l in open("state/signals.jsonl") if l.strip()]
first = {}
for s in sig:
    if s["ts"] >= t0 and (s.get("sol") or 0) >= 1: first.setdefault(s["mint"], s)
tw = [r for r in rows if r["is_tweet"]]
seen = [m for m in first if m in by]
print(f"sombra desde {time.strftime('%H:%M', time.gmtime(t0 - 3*3600))} ART: {len(rows)} creados, {len(tw)} de tweet ({len(tw)/len(rows):.0%})")
print(f"compras grandes de decu: {len(first)} | vistas por la sombra: {len(seen)} ({len(seen)/max(len(first),1):.0%}) | de tweet: {sum(by[m]['is_tweet'] for m in seen)}")
med = lambda v: (sorted(x for x in v if x is not None) or [None])[len([x for x in v if x is not None])//2]
pick = [by[m] for m in seen if by[m]["is_tweet"]]; nopick = [r for r in tw if r["mint"] not in first]
for name, g in (("COMPRADOS por decu", pick), ("tweet NO comprados", nopick)):
    print(f"\n{name}: n={len(g)}")
    print("  tweet->creación s: mediana", med([r.get("tweet_to_create_s") for r in g]))
    print("  herramienta:", Counter(r["meta_src"] for r in g).most_common(5))
    print("  autores:", Counter(r.get("tweet_author") for r in g).most_common(10))
    print("  mint sin 'pump':", sum(1 for r in g if not r["mint"].endswith("pump")), "| con web:", sum(1 for r in g if r["website"]))
print("decu: segundos desde la creación hasta su compra:", sorted(round(first[m]["ts"] - by[m]["seen_ts"], 1) for m in seen)[:40])
# grupos por tweet
tid = lambda r: r["twitter"].split("/status/")[1].split("?")[0].split("/")[0]
grp = {}
for r in tw: grp.setdefault(tid(r), []).append(r)
for k in {tid(by[m]) for m in seen if by[m]["is_tweet"]}:
    v = sorted(grp[k], key=lambda x: x["seen_ts"])
    print("  tweet de", v[0].get("tweet_author"), "| tokens del tweet:", len(v), "| decu compró #", [i+1 for i, x in enumerate(v) if x["mint"] in first], "|", [x["symbol"] for x in v][:5])

def candles(m, c0):
    for i in range(3):
        try:
            r = requests.get(f"{ST}/chart/{m}", headers=H, params={"type": "1s", "time_from": int(c0) - 2, "time_to": int(c0) + 200}, timeout=30)
            if r.ok: return [(int(c["time"]), float(c["close"]), float(c["high"]), float(c["low"])) for c in r.json().get("oclhv", [])]
        except Exception: pass
        time.sleep(1)
    return []

def sim(m, c0, entry_s, exit_s=80, slip=0.08, stop=0.35, tp=1.0):
    cs = candles(m, c0)
    if not cs: return None
    pre = [c for c in cs if c[0] <= c0 + entry_s]
    if not pre: return None
    px = pre[-1][1] * (1 + slip)
    for t, cl, hi, lo in cs:
        if t <= c0 + entry_s: continue
        if lo <= px * (1 - stop): return -stop - 0.02
        if hi >= px * (1 + tp): return tp - 0.02
        if t >= c0 + exit_s: return cl / px * (1 - 0.02) - 1
    return cs[-1][1] / px * (1 - 0.02) - 1

random.seed(1)
samp = random.sample(nopick, min(60, len(nopick)))
res = {}
for name, g in (("COMPRADOS", pick), ("NO comprados (muestra)", samp)):
    for es in (2, 5):
        rr = [x for x in (sim(r["mint"], r["seen_ts"], es) for r in g) if x is not None]
        if rr:
            print(f"SIM {name} entrada seg {es}: n={len(rr)} acierto {sum(x>0 for x in rr)/len(rr):.0%} mediana {med(rr):+.2f} media {sum(rr)/len(rr):+.3f}")
