"""¿La "fábrica de marcas" (TESLA SI, SpaceX AI, Grok, NVIDIA, Rockstar, YouTube...) tiene un fondeador común? (31/10/2026)
Si los creadores de los tokens con nombre de marca que bombean salen de las mismas billeteras madre, se puede vigilar
a la madre y comprar al instante de la creación (en el piso, antes del bombeo). Dos saltos de fondeo por Helius."""
import json, time, collections
from pathlib import Path
from fomo_intel.desk.dd import funder_helius, funder_rpc
OUT = Path("state/research/brand_factory.json")
toks = json.load(open("research/brand_tokens_31_10.json"))
cache = {}
def fund(a):
    if not a: return None
    if a in cache: return cache[a]
    f = funder_helius(a) or funder_rpc(a)
    cache[a] = (f or {}).get("funder"); time.sleep(0.15)
    return cache[a]
t0 = time.time()
for i, t in enumerate(toks):
    t["f1"] = fund(t.get("dev")); t["f2"] = fund(t["f1"]) if t["f1"] else None
    if i % 50 == 0:
        print(i, len(toks), round(time.time() - t0), flush=True)
        json.dump(toks, open(OUT, "w"))
json.dump(toks, open(OUT, "w"))
for lvl in ("f1", "f2"):
    pumped = collections.Counter(t[lvl] for t in toks if t[lvl] and t["peak"] >= 100000)
    allc = collections.Counter(t[lvl] for t in toks if t[lvl])
    print(f"--- {lvl}: fondeadores más repetidos entre las que bombearon (bombearon/total con ese fondeador)")
    for f, n in pumped.most_common(12):
        print(f"  {f}  {n}/{allc[f]}")
print("OK")
