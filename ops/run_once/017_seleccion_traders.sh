#!/bin/bash
# Selección de traders a copiar: ranking 30 d y 7 d de Solana Tracker, filtros de actividad/acierto, y perfil de sus últimas operaciones.
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 - <<'PY'
import json, os, requests, time
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"
def get(path, **p):
    r = requests.get(B + path, headers=h, params=p, timeout=30); r.raise_for_status(); return r.json()
cands = {}
for days in (30, 7):
    for sort in ("win_percentage", "realized", "roi", "trades"):
        for direction in ("desc",):
            try:
                d = get("/v2/pnl/leaderboard/top", days=days, sort=sort, direction=direction, limit=100)
            except Exception as e:
                print("leaderboard", days, sort, "error", e); continue
            for t in d.get("traders", []):
                w = t["wallet"]; per = t.get("period", {}); cnt = t.get("counts", {}); tk = t.get("tokens", {}); av = t.get("averages", {}); tm = t.get("timing", {})
                row = {"wallet": w, "days": days, "winRate": t.get("winRate"), "tokens": cnt.get("tokensTraded"), "trades": cnt.get("trades"),
                       "closed": tk.get("closed"), "prof": tk.get("profitable"), "los": tk.get("losing"), "realized": per.get("realized"), "roi": per.get("roi"),
                       "invested": t.get("invested"), "avg_buy": av.get("buy"), "avg_sell": av.get("sell"), "tradingDays": per.get("tradingDays"),
                       "days_prof": (per.get("days") or {}).get("profitable"), "days_los": (per.get("days") or {}).get("losing"),
                       "last_trade_h": round((time.time()*1000 - (tm.get("lastTrade") or 0)) / 3.6e6, 1), "strict_mode": (t.get("pnlAdjustments") or {}).get("mode")}
                key = (w, days)
                cands[key] = row
print(f"candidatos únicos: {len({w for w,_ in cands})}")
def ok(r):
    return (r["winRate"] or 0) >= 60 and (r["tokens"] or 0) >= 25 and (r["trades"] or 0) >= 60 and 20 <= (r["avg_buy"] or 0) <= 5000 \
        and r["last_trade_h"] <= 48 and (r["realized"] or 0) > 0 and (r["roi"] or 0) < 2000 and (r["days_prof"] or 0) > (r["days_los"] or 0)
sel = sorted([r for r in cands.values() if ok(r)], key=lambda r: (-r["winRate"], -(r["tokens"] or 0)))
print(f"pasan filtros (acierto>=60%, >=25 tokens, >=60 trades, compra media US$20-5000, activo 48h, ROI<2000%): {len(sel)}")
print(f"{'wallet':<46}{'d':>3}{'win%':>6}{'tok':>5}{'trd':>6}{'avg$':>8}{'realiz$':>11}{'roi%':>8}{'dias+/-':>9}{'ult h':>7}")
for r in sel[:60]:
    print(f"{r['wallet']:<46}{r['days']:>3}{r['winRate']:>6.0f}{r['tokens']:>5}{r['trades']:>6}{r['avg_buy']:>8.0f}{r['realized']:>11,.0f}{r['roi']:>8.0f}{str(r['days_prof'])+'/'+str(r['days_los']):>9}{r['last_trade_h']:>7}")
# perfil de operaciones de los 15 mejores: ¿operan tokens pump? ¿cuánto tardan en vender?
print("\n== perfil de últimas 40 operaciones (15 mejores) ==")
prof = []
for r in sel[:15]:
    try:
        d = get(f"/wallet/{r['wallet']}/trades", limit=40)
    except Exception as e:
        print(r["wallet"][:8], "sin trades", e); continue
    tr = d.get("trades", [])
    buys = {}; holds = []; pump = 0; n = 0
    for t in sorted(tr, key=lambda x: x.get("time", 0)):
        frm, to = t.get("from", {}), t.get("to", {})
        ts = t.get("time", 0) / 1000
        if frm.get("address", "").startswith("So111"):          # compra
            mint = to.get("address", ""); buys[mint] = ts; n += 1; pump += mint.endswith("pump")
        elif to.get("address", "").startswith("So111"):         # venta
            mint = frm.get("address", "")
            if mint in buys: holds.append((ts - buys[mint]) / 60)
    med = sorted(holds)[len(holds)//2] if holds else None
    row = {"wallet": r["wallet"], "winRate": r["winRate"], "tokens30": r["tokens"], "n_buys": n, "pump_share": round(pump / n, 2) if n else None,
           "hold_med_min": round(med, 1) if med is not None else None, "avg_buy": r["avg_buy"]}
    prof.append(row); print(row)
json.dump({"selected": sel, "profiles": prof}, open("state/ops/traders.json", "w"), indent=1)
PY
