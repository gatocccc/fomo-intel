#!/bin/bash
# ¿Cuántas x hace un token comprado al minuto 3 (después de la primera ola) y holdeado hasta la graduación?
# Momento de graduación = createdAt del pool de PumpSwap (pumpfun-amm) en /tokens/{mint}. Precio = cierre de la vela de 1 m en ese minuto.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 590 python3 -u - <<'PY' 9>&-
import json, os, time, requests, statistics as st
from pathlib import Path
D = Path("data/exp_red"); h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
cache_p = D / "grad_times.json"; cache = json.load(open(cache_p)) if cache_p.exists() else {}
rows = {}
for name in ("pump", "pump7"):
    for l in open(D / f"{name}_tokens.jsonl"):
        r = json.loads(l)
        if r.get("n_candles", 0) >= 3: rows[r["mint"]] = r
print("tokens con velas:", len(rows))
ENTRY_MIN, COST = 3, 1.06   # entrada al cierre del minuto 3 + 5% slippage + 1% fee
SELL = 0.94                 # salida: -5% slippage -1% fee
res = []
for i, (mint, r) in enumerate(rows.items()):
    cs = json.load(open(D / "charts" / f"{mint}.json"))["m1"]
    c0 = next((c for c in cs if c["t"] >= r["created"] + ENTRY_MIN * 60), None)
    if not c0 or c0["t"] > r["created"] + 5 * 60 or c0["c"] <= 0: continue
    entry = c0["c"] * COST
    first = cs[0]["o"] or cs[0]["c"]
    g = cache.get(mint)
    if g is None and r.get("status") in ("graduated", "graduating"):
        info = requests.get(f"{B}/tokens/{mint}", headers=h, timeout=30).json(); time.sleep(0.25)
        amm = [p for p in info.get("pools") or [] if (p.get("market") or "") in ("pumpfun-amm", "pumpswap", "raydium", "meteora-dyn-v2", "raydium-cpmm")]
        t = min((p.get("createdAt") or 9e18) for p in amm) if amm else None
        g = int(t / 1000) if t and t > 1e11 else (int(t) if t else 0)
        cache[mint] = g
    elif g is None:
        g = 0
    after = [c for c in cs if c["t"] > c0["t"]]
    rec = {"mint": mint, "sym": r.get("symbol"), "entry_mult_desde_lanz": c0["c"] / first if first else None, "grad": bool(g)}
    if g and g > c0["t"]:
        cg = [c for c in cs if c["t"] <= g + 60]
        px_g = cg[-1]["c"] if cg else None
        pre = [c for c in after if c["t"] <= g]
        rec.update(x_grad=px_g * SELL / entry if px_g else None, min_hasta=(g - r["created"]) / 60,
                   peor_antes=min(c["l"] for c in pre) / entry if pre else None, pico_antes=max(c["h"] for c in pre) / entry if pre else None)
        post = [c for c in cs if g < c["t"] <= g + 3600]
        rec["pico_1h_post"] = max(c["h"] for c in post) * SELL / entry if post else None
        rec["x_1h_post"] = post[-1]["c"] * SELL / entry if post else None
    elif g and g <= c0["t"]:
        rec["grad_antes_de_entrar"] = True
    else:
        last = after[-1]["c"] if after else c0["c"]
        rec["x_final_sin_grad"] = last * SELL / entry * 0.5  # sin graduar: lo que queda, con castigo por liquidez
    res.append(rec)
json.dump(cache, open(cache_p, "w"))
gr = [x for x in res if x.get("x_grad")]
ng = [x for x in res if "x_final_sin_grad" in x]
pre = [x for x in res if x.get("grad_antes_de_entrar")]
print(f"\nentradas al minuto {ENTRY_MIN}: {len(res)} | graduaron DESPUÉS de entrar: {len(gr)} ({len(gr)/len(res):.1%}) | ya habían graduado: {len(pre)} | no graduaron: {len(ng)}")
q = lambda v, p: sorted(v)[min(len(v)-1, int(p*len(v)))]
xs = [x["x_grad"] for x in gr]
print(f"\nX AL MOMENTO DE GRADUAR (neto de costos), {len(xs)} tokens:")
print(f"   mediana {st.median(xs):.2f}x | promedio {sum(xs)/len(xs):.2f}x | p25 {q(xs,.25):.2f}x | p75 {q(xs,.75):.2f}x | p90 {q(xs,.9):.2f}x | min {min(xs):.2f}x | max {max(xs):.2f}x")
print(f"   con x<1 (perdés aun graduando): {sum(1 for v in xs if v<1)/len(xs):.0%}")
mins = [x["min_hasta"] for x in gr]; print(f"   minutos desde el lanzamiento hasta graduar: mediana {st.median(mins):.0f}, p75 {q(mins,.75):.0f}, p90 {q(mins,.9):.0f}")
pa = [x["peor_antes"] for x in gr if x.get("peor_antes")]; print(f"   peor caída en el camino (precio/entrada): mediana {st.median(pa):.2f}, p25 {q(pa,.25):.2f} | bajaron >40% antes de graduar: {sum(1 for v in pa if v<0.6)/len(pa):.0%}")
em = [x["entry_mult_desde_lanz"] for x in gr if x.get("entry_mult_desde_lanz")]; print(f"   ya había subido al minuto 3 (vs primer precio): mediana {st.median(em):.1f}x")
p1 = [x["pico_1h_post"] for x in gr if x.get("pico_1h_post")]; x1 = [x["x_1h_post"] for x in gr if x.get("x_1h_post")]
if p1: print(f"   1 h después de graduar: pico mediano {st.median(p1):.2f}x, cierre mediano {st.median(x1):.2f}x")
nv = [x["x_final_sin_grad"] for x in ng]
print(f"\nNO GRADUARON ({len(nv)}): valor final mediano {st.median(nv):.2f}x de lo invertido")
p = len(gr) / (len(gr) + len(ng))
ev = p * (sum(xs)/len(xs)) + (1-p) * (sum(nv)/len(nv))
print(f"\nESTRATEGIA 'comprar al min 3 y holdear hasta graduar (o hasta que muera)': prob. graduar {p:.1%} | valor esperado por US$1 = {ev:.2f} ({ev-1:+.0%})")
# por grupo de creador
for lab, sel in (("creador con >=1 graduación previa", lambda r: sum(1 for x in ((r.get('dev_hist') or {}).get('prior') or []) if x.get('graduated'))>=1),):
    g2 = [x for x in gr if sel(rows[x["mint"]])]; n2 = [x for x in ng if sel(rows[x["mint"]])]
    if g2 and n2:
        p2 = len(g2)/(len(g2)+len(n2)); xs2=[x["x_grad"] for x in g2]; e2 = p2*sum(xs2)/len(xs2)+(1-p2)*sum(x["x_final_sin_grad"] for x in n2)/len(n2)
        print(f"   {lab}: prob. graduar {p2:.1%} (n={len(g2)+len(n2)}) | x mediana al graduar {st.median(xs2):.2f}x | valor esperado {e2:.2f}")
print("\nejemplos:", [(x["sym"], round(x["x_grad"],2), round(x["min_hasta"])) for x in sorted(gr, key=lambda x: x["x_grad"])[::max(1,len(gr)//10)]])
PY
