#!/bin/bash
# Corte parcial del modo sombra (ops 076) cruzado con las compras de decu de hoy.
cd /root/fomo_intel
tail -3 state/ops/076_detalle.txt
python3 - <<'PY'
import json, time
from collections import Counter
rows=[json.loads(l) for l in open("state/tweetshadow/creates.jsonl")]
by={r["mint"]:r for r in rows}
t0=min(r["seen_ts"] for r in rows)
print(f"registrados: {len(rows)} desde {time.strftime('%H:%M',time.localtime(t0-3*3600))} ART | con tweet: {sum(r['is_tweet'] for r in rows)} | metadatos ok: {sum(1 for r in rows if not r['meta_src'].startswith('fail'))}")
sig=[json.loads(l) for l in open("state/signals.jsonl") if l.strip()]
buys=[s for s in sig if s["ts"]>=t0 and (s.get("sol") or 0)>=1]
first={}
for s in buys: first.setdefault(s["mint"], s)
print(f"compras grandes de decu desde que arrancó la sombra: {len(first)} tokens")
hit=[m for m in first if m in by]
print(f"de esas, vistas por la sombra: {len(hit)} ({len(hit)/max(len(first),1):.0%})")
tw=[r for r in rows if r["is_tweet"]]
picked=[by[m] for m in hit]
print("compradas con tweet:", sum(r["is_tweet"] for r in picked), "de", len(picked))
def med(v):
    v=sorted(x for x in v if x is not None); return v[len(v)//2] if v else None
for name,grp in (("compradas por decu",[r for r in picked if r["is_tweet"]]),("tweet NO compradas",[r for r in tw if r["mint"] not in first])):
    print(f"\n{name}: n={len(grp)}")
    print("  tweet->creación s mediana", med([r.get("tweet_to_create_s") for r in grp]))
    print("  herramienta", Counter(r["meta_src"] for r in grp).most_common(5))
    print("  autores", Counter(r.get("tweet_author") for r in grp).most_common(8))
    print("  init_sol mediana", med([r.get("init_sol") for r in grp]), "| mcap_sol mediana", med([r.get("mcap_sol") for r in grp]))
# por tweet: cuántos tokens hubo y si decu compró alguno
tid=lambda r: r["twitter"].split("/status/")[1].split("?")[0][:25]
grp={}
for r in tw: grp.setdefault(tid(r),[]).append(r)
multi=Counter(len(v) for v in grp.values())
print("\ntokens por tweet:", sorted(multi.items())[:10])
bought_t=[k for k,v in grp.items() if any(x["mint"] in first for x in v)]
print("tweets con compra de decu:", len(bought_t), "de", len(grp))
print("  tamaño del grupo en esos tweets:", sorted(len(grp[k]) for k in bought_t))
for k in bought_t[:12]:
    v=sorted(grp[k],key=lambda x:x["seen_ts"]); idx=[i for i,x in enumerate(v) if x["mint"] in first]
    print("  ", v[0].get("tweet_author"), "| tokens:", len(v), "| decu compró el #", [i+1 for i in idx], "|", [x["symbol"] for x in v][:6])
for m in first:
    if m not in by: print("  no visto:", m[:10], round((first[m]["ts"]-t0)/60), "min")
PY
