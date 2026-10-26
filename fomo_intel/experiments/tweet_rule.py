"""Reglas candidatas, calculables al crearse el token (sin saber qué hace decu): precisión vs compras de decu y simulación
entrando al seg 2 sobre TODOS los tokens que cumplen la regla (muestra), no solo los que eligió decu."""
import json, random, time
from collections import Counter, defaultdict
from fomo_intel.experiments import tweet_sim as T   # reutiliza datos cargados, candles(), sim()
rows = sorted(T.rows, key=lambda r: r["seen_ts"]); first = T.first
# rango del token dentro de su tweet (en el momento de crearse)
cnt = defaultdict(int)
for r in rows:
    if r["is_tweet"]:
        k = T.tid(r); cnt[k] += 1; r["rank"] = cnt[k]
auth_n = Counter(r.get("tweet_author") for r in rows if r["is_tweet"])
tw = [r for r in rows if r["is_tweet"] and r.get("tweet_to_create_s") is not None]
print("compras de decu en tokens de tweet vistos:", sum(1 for r in tw if r["mint"] in first))
print("rango de lo que compra decu:", Counter(min(r["rank"], 6) for r in tw if r["mint"] in first))
print("tweet->creación de lo que compra decu:", sorted(round(r["tweet_to_create_s"]) for r in tw if r["mint"] in first))
rules = {
  "R1 rank1 & tw<=10s": lambda r: r["rank"] == 1 and r["tweet_to_create_s"] <= 10,
  "R2 rank1 & tw<=20s": lambda r: r["rank"] == 1 and r["tweet_to_create_s"] <= 20,
  "R3 rank1 & tw<=10s & j7": lambda r: r["rank"] == 1 and r["tweet_to_create_s"] <= 10 and "j7tracker" in r["meta_src"],
  "R4 rank<=2 & tw<=15s": lambda r: r["rank"] <= 2 and r["tweet_to_create_s"] <= 15,
  "R5 rank1 & 0<tw<=8s & web": lambda r: r["rank"] == 1 and 0 < r["tweet_to_create_s"] <= 8 and bool(r["website"]),
}
hours = (rows[-1]["seen_ts"] - rows[0]["seen_ts"]) / 3600
random.seed(2)
for name, f in rules.items():
    sel = [r for r in tw if f(r)]
    hit = sum(1 for r in sel if r["mint"] in first)
    cap = sum(1 for r in tw if r["mint"] in first and f(r))
    print(f"\n{name}: {len(sel)} tokens ({len(sel)/hours:.0f}/h) | decu compró {hit} ({hit/max(len(sel),1):.0%} precisión) | captura {cap}/{sum(1 for r in tw if r['mint'] in first)} de sus compras")
    samp = random.sample(sel, min(70, len(sel)))
    rr = [(x, r["mint"] in first) for r in samp for x in [T.sim(r["mint"], r["seen_ts"], 2)] if x is not None]
    if rr:
        v = [x for x, _ in rr]
        print(f"   SIM seg 2 (muestra {len(v)}): acierto {sum(x>0 for x in v)/len(v):.0%} mediana {T.med(v):+.2f} media {sum(v)/len(v):+.3f} | "
              f"sin los que compró decu: media {sum(x for x,d in rr if not d)/max(1,sum(1 for _,d in rr if not d)):+.3f}")
# latencia de metadatos al primer intento (lo que tendríamos en vivo)
lat = sorted(r["meta_lat_s"] for r in tw)
print("\nlatencia metadatos tokens de tweet: p50", lat[len(lat)//2], "p75", lat[3*len(lat)//4], "| <=1s:", f"{sum(x<=1 for x in lat)/len(lat):.0%}")
