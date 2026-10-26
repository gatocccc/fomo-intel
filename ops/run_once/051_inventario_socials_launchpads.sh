#!/bin/bash
# Experimentos 1 y 2 (26/10): inventario de lo que ya tenemos para medir "red detrás" del token.
#  a) en launches_raw: campos sociales (twitter/telegram/website), launchpad, creador; graduación según socials
#  b) ¿el dev vendió antes de graduar? (first_buyers con is_developer)
#  c) ST: qué mercados/launchpads aparecen en /tokens/latest y qué devuelve /search para bags
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 500 python3 -u - <<'PY'
import json, os, glob, requests, time
from collections import Counter, defaultdict
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
raws = glob.glob("data/launches_raw/*.json"); print("launches_raw:", len(raws), "| launches:", len(glob.glob("data/launches/*.json")), "| charts:", len(glob.glob("data/charts/*.json")))
keys_tok = Counter(); keys_top = Counter(); lp = Counter(); soc = Counter(); grad_by = defaultdict(lambda: [0, 0]); sample = None
devsold = defaultdict(lambda: [0, 0])  # (dev_vendio, graduado)
for p in raws:
    try: info = json.load(open(p))
    except Exception: continue
    tk = info.get("token") or {}; keys_top.update(info.keys()); keys_tok.update(tk.keys())
    pools = info.get("pools") or [{}]
    curve = min(pools, key=lambda x: x.get("createdAt") or 9e18)
    m = (curve.get("market") or "").replace("-curve", ""); lp[m] += 1
    graduated = len(pools) > 1 or (curve.get("curvePercentage") or 0) >= 100
    tw = bool(tk.get("twitter")); tg = bool(tk.get("telegram")); web = bool(tk.get("website"))
    key = ("tw" if tw else "-") + ("tg" if tg else "-") + ("web" if web else "-")
    soc[key] += 1; g = grad_by[key]; g[0] += 1; g[1] += int(graduated)
    if sample is None and (tw or tg): sample = {k: tk.get(k) for k in ("name", "symbol", "twitter", "telegram", "website", "createdOn", "showName", "description")}
print("campos top:", sorted(keys_top)); print("campos token:", sorted(keys_tok)); print("ejemplo con socials:", sample)
print("launchpads:", lp.most_common(12))
print("socials (tw/tg/web) -> n, graduados, tasa:")
for k, (n, g) in sorted(grad_by.items(), key=lambda x: -x[1][0]): print(f"   {k:<10} n={n:5d} grad={g:4d} {g/n:.1%}")
# dev vendió antes/graduación (de launches con first_buyers)
for p in glob.glob("data/launches/*.json"):
    d = json.load(open(p))
    if d.get("partial"): continue
    dev = [b for b in d["first_buyers"] if b.get("is_developer")]
    if not dev: continue
    sold = dev[0]["sells"] > 0
    x = devsold[("dev_vendio" if sold else "dev_no_vendio")]; x[0] += 1; x[1] += int(d["graduated"])
print("dev vendió vs graduación:", {k: (n, g, round(g/n, 3)) for k, (n, g) in devsold.items()})
# ST: mercados en latest
r = requests.get(f"{B}/tokens/latest", headers=h, timeout=30); L = r.json() if r.ok else []
mk = Counter();
for t in (L if isinstance(L, list) else L.get("data", [])):
    for pl in t.get("pools") or []: mk[pl.get("market")] += 1
print("mercados en /tokens/latest:", mk.most_common(15))
# ST search por bags
for params in ({"market": "bags", "limit": 50}, {"market": "bags-curve", "limit": 50}, {"query": "", "market": "bags", "sortBy": "createdAt", "limit": 50}):
    try:
        r = requests.get(f"{B}/search", headers=h, params=params, timeout=30)
        d = r.json() if r.ok else {}
        data = d.get("data", d if isinstance(d, list) else [])
        print("search", params, "->", r.status_code, "n=", len(data), "| ej:", (data[0] if data else d if not r.ok else ""))
        if data: print("   campos:", sorted(data[0].keys()))
    except Exception as e: print("search err", params, e)
    time.sleep(0.5)
# Bags API pública: probar sin clave
for u in ("https://public-api-v2.bags.fm/api/v1/token-launch/leaderboard", "https://api2.bags.fm/api/v1/token-launch/leaderboard", "https://bags.fm/api/v1/token-launch/leaderboard"):
    try:
        r = requests.get(u, timeout=20); print("bags", u, "->", r.status_code, r.text[:300].replace("\n", " "))
    except Exception as e: print("bags", u, "err", e)
print("BAGS_API_KEY en .env:", bool(os.environ.get("BAGS_API_KEY")))
PY
