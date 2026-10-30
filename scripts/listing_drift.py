"""¿Los perps recién listados en Hyperliquid caen en sus primeras 1–2 semanas? (30/10, cola del lab). Corto al cierre del día 1,
salida día 7 / 14, cubierto con BTC (retorno del token menos el de BTC), costo 0,3% ida y vuelta. Control: ventanas al azar de los
mismos tokens después del día 30."""
import json, random, statistics as stx, time, math
import requests
HL = "https://api.hyperliquid.xyz/info"
meta = requests.post(HL, json={"type": "meta"}, timeout=30).json()["universe"]
def d1(c, start):
    r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": c, "interval": "1d", "startTime": start, "endTime": int(time.time()*1000)}}, timeout=30)
    return [(int(x["t"])//1000, float(x["c"])) for x in (r.json() if r.ok else [])]
t0 = int(time.mktime((2023, 6, 1, 0, 0, 0, 0, 0, 0)) * 1000)
btc = dict(d1("BTC", t0)); res = {7: [], 14: []}; ctl = {7: [], 14: []}; rnd = random.Random(1); n = 0
for u in meta:
    c = u["name"]
    if c in ("BTC",) or u.get("isDelisted"): continue
    rows = d1(c, t0); time.sleep(0.15)
    if len(rows) < 20 or rows[0][0] * 1000 < t0 + 5 * 86400000: continue   # listado antes de jun-2023 (o sin historia): no es un listado nuevo
    n += 1
    for H in (7, 14):
        if len(rows) > 1 + H and rows[1][0] in btc and rows[1 + H][0] in btc:
            r = -(rows[1 + H][1] / rows[1][1] - 1) + (btc[rows[1 + H][0]] / btc[rows[1][0]] - 1) - 0.003
            res[H].append(r)
        for _ in range(3):
            if len(rows) > 30 + H + 5:
                i = rnd.randrange(30, len(rows) - H)
                if rows[i][0] in btc and rows[i + H][0] in btc:
                    ctl[H].append(-(rows[i + H][1] / rows[i][1] - 1) + (btc[rows[i + H][0]] / btc[rows[i][0]] - 1) - 0.003)
print("listados nuevos desde jun-2023:", n)
for H in (7, 14):
    x = res[H]; y = ctl[H]
    if len(x) > 5:
        print(f"corto día1→día{H}: n {len(x)} aciertos {sum(1 for v in x if v > 0)/len(x):.0%} media {stx.mean(x):+.2%} mediana {stx.median(x):+.2%} t {stx.mean(x)/stx.pstdev(x)*math.sqrt(len(x)):+.2f} | azar media {stx.mean(y):+.2%} n {len(y)}")
    # por año
    print("  (recortado al 5–95% para sacar extremos):", f"{stx.mean(sorted(x)[len(x)//20: -len(x)//20 or None]):+.2%}")
