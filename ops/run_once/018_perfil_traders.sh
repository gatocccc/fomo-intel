#!/bin/bash
# Perfil operativo de los 206 traders preseleccionados: tiempo de tenencia, % pump, mcap al comprar, frecuencia. Elige la lista a seguir.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests, time, statistics as st
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
sel = json.load(open("state/ops/traders.json"))["selected"]
seen = set(); out = []
for r in sel:
    w = r["wallet"]
    if w in seen: continue
    seen.add(w)
    try:
        d = requests.get(f"{B}/wallet/{w}/trades", headers=h, params={"limit": 100}, timeout=30).json()
    except Exception as e:
        continue
    tr = sorted(d.get("trades", []), key=lambda x: x.get("time", 0))
    buys = {}; holds = []; mcaps = []; n_b = n_s = pump = 0; sizes = []
    for t in tr:
        frm, to = t.get("from", {}), t.get("to", {}); ts = t.get("time", 0) / 1000
        if frm.get("address", "").startswith("So111"):
            mint = to.get("address", ""); buys.setdefault(mint, ts); n_b += 1; pump += mint.endswith("pump")
            if to.get("marketCap"): mcaps.append(to["marketCap"])
            sizes.append(frm.get("amount", 0))
        elif to.get("address", "").startswith("So111"):
            mint = frm.get("address", ""); n_s += 1
            if mint in buys: holds.append((ts - buys.pop(mint)) / 60)
    span_h = (tr[-1]["time"] - tr[0]["time"]) / 3.6e6 if len(tr) > 1 else 0
    row = {"wallet": w, "winRate": r["winRate"], "tokens30": r["tokens"], "trades30": r["trades"], "avg_buy_usd": r["avg_buy"], "realized": r["realized"],
           "n_buys": n_b, "pump_share": round(pump / n_b, 2) if n_b else None,
           "hold_med_min": round(st.median(holds), 1) if holds else None, "hold_p25_min": round(sorted(holds)[len(holds)//4], 1) if len(holds) >= 4 else None,
           "mcap_med": round(st.median(mcaps)) if mcaps else None, "buy_sol_med": round(st.median(sizes), 3) if sizes else None,
           "buys_per_h": round(n_b / span_h, 2) if span_h else None, "last_h": r["last_trade_h"]}
    out.append(row)
def follow_ok(p):
    return (p["hold_med_min"] or 0) >= 3 and (p["pump_share"] or 0) >= 0.6 and (p["mcap_med"] or 1e9) <= 150_000 and (p["winRate"] or 0) >= 65 \
        and 15 <= (p["tokens30"] or 0) <= 600 and (p["buys_per_h"] or 0) <= 6 and (p["buy_sol_med"] or 0) >= 0.1
fl = sorted([p for p in out if follow_ok(p)], key=lambda p: (-p["winRate"], -p["tokens30"]))
print(f"perfilados: {len(out)} ; seguibles (tenencia mediana >=3 min, >=60% pump, mcap mediana <=150K, acierto >=65%, 15-600 tokens/30d, <=6 compras/h, compra mediana >=0.1 SOL): {len(fl)}")
print(f"{'wallet':<46}{'win%':>5}{'tok30':>6}{'avg$':>7}{'hold':>7}{'p25':>6}{'mcap':>9}{'sol':>6}{'c/h':>6}{'pump':>6}{'real$':>10}")
for p in fl:
    print(f"{p['wallet']:<46}{p['winRate']:>5.0f}{p['tokens30']:>6}{p['avg_buy_usd']:>7.0f}{p['hold_med_min']:>7}{str(p['hold_p25_min']):>6}{p['mcap_med']:>9,}{p['buy_sol_med']:>6}{p['buys_per_h']:>6}{p['pump_share']:>6}{p['realized']:>10,.0f}")
json.dump({"profiles": out, "follow": fl}, open("state/ops/traders_perfil.json", "w"), indent=1)
json.dump({"wallets": [p["wallet"] for p in fl], "updated": time.time()}, open("state/follow_list.json", "w"), indent=1)
print("\nlista guardada en state/follow_list.json:", len(fl))
PY
