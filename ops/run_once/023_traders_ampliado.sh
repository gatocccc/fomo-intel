#!/bin/bash
# Búsqueda ampliada de traders copiables: top-traders paginado + leaderboard 1/3/7 d; perfil de operaciones; exige actividad en 12 h.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u - <<'PY'
import json, os, requests, time, statistics as st
h = {"x-api-key": os.environ["SOLANATRACKER_API_KEY"]}; B = "https://data.solanatracker.io"; now = time.time()
def get(path, **p):
    r = requests.get(B + path, headers=h, params=p, timeout=30); r.raise_for_status(); return r.json()
cand = {}
for sort in ("total", "winPercentage"):
    for page in range(1, 9):
        try: d = get(f"/top-traders/all/{page}", sortBy=sort, expandPnl="true")
        except Exception as e: print("top-traders", sort, page, e); break
        for w in d.get("wallets", []):
            s = w.get("summary", {}); n = (s.get("totalWins") or 0) + (s.get("totalLosses") or 0)
            cand[w["wallet"]] = {"src": f"tt-{sort}", "win": s.get("winPercentage"), "n": n, "avg": s.get("averageBuyAmount"), "realized": s.get("realized")}
for days in (1, 3, 7):
    for sort in ("win_percentage", "trades", "realized"):
        try: d = get("/v2/pnl/leaderboard/top", days=days, sort=sort, direction="desc", limit=100)
        except Exception as e: print("lb", days, sort, e); continue
        for t in d.get("traders", []):
            cnt = t.get("counts", {}); tm = t.get("timing", {})
            cand.setdefault(t["wallet"], {"src": f"lb{days}-{sort}", "win": t.get("winRate"), "n": cnt.get("trades"), "avg": (t.get("averages") or {}).get("buy"), "realized": (t.get("period") or {}).get("realized")})
            cand[t["wallet"]]["last_h"] = round((now*1000 - (tm.get("lastTrade") or 0)) / 3.6e6, 1)
print("candidatos:", len(cand))
pre = [(w, c) for w, c in cand.items() if (c.get("win") or 0) >= 60 and (c.get("n") or 0) >= 40 and 15 <= (c.get("avg") or 0) <= 3000 and (c.get("last_h") is None or c["last_h"] <= 24)]
print("prefiltro (acierto>=60, >=40 ops, compra media 15-3000):", len(pre))
out = []
for i, (w, c) in enumerate(pre):
    if time.time() - now > 500: print("tiempo agotado en", i); break
    try: tr = sorted(get(f"/wallet/{w}/trades", limit=50).get("trades", []), key=lambda x: x.get("time", 0))
    except Exception: continue
    if not tr: continue
    last_h = (now - tr[-1]["time"]/1000) / 3600
    if last_h > 12: continue
    buys = {}; holds = []; mcaps = []; sizes = []; n_b = 0; pump = 0
    for t in tr:
        frm, to = t.get("from", {}), t.get("to", {}); ts = t.get("time", 0) / 1000
        if frm.get("address", "").startswith("So111"):
            m = to.get("address", ""); buys.setdefault(m, ts); n_b += 1; pump += (t.get("program") or "").startswith("pump")
            if to.get("marketCap"): mcaps.append(to["marketCap"])
            sizes.append(frm.get("amount", 0))
        elif to.get("address", "").startswith("So111"):
            m = frm.get("address", "")
            if m in buys: holds.append((ts - buys.pop(m)) / 60)
    span_h = max(0.1, (tr[-1]["time"] - tr[0]["time"]) / 3.6e6)
    row = {"wallet": w, **c, "last_h": round(last_h, 1), "n_buys": n_b, "pump_share": round(pump / n_b, 2) if n_b else 0,
           "hold_med": round(st.median(holds), 1) if holds else None, "hold_p25": round(sorted(holds)[len(holds)//4], 1) if len(holds) >= 4 else None,
           "mcap_med": round(st.median(mcaps)) if mcaps else None, "sol_med": round(st.median(sizes), 3) if sizes else None, "buys_h": round(n_b / span_h, 2)}
    out.append(row)
ok = [r for r in out if (r["hold_med"] or 0) >= 3 and (r["hold_p25"] or 0) >= 1 and r["pump_share"] >= 0.5 and (r["mcap_med"] or 9e9) <= 300000 and (r["sol_med"] or 0) >= 0.05 and r["buys_h"] <= 8]
ok.sort(key=lambda r: (-(r["win"] or 0), -r["n"]))
print(f"activos en 12 h: {len(out)} ; copiables (tenencia med >=3 min y p25 >=1, >=50% pump, mcap med <=300K, compra med >=0.05 SOL, <=8 compras/h): {len(ok)}")
print(f"{'wallet':<46}{'src':>16}{'win%':>5}{'n':>7}{'avg$':>7}{'hold':>6}{'p25':>6}{'mcap':>9}{'sol':>6}{'c/h':>5}{'ult h':>6}")
for r in ok: print(f"{r['wallet']:<46}{r['src']:>16}{r['win']:>5.0f}{r['n']:>7}{r['avg']:>7.0f}{str(r['hold_med']):>6}{str(r['hold_p25']):>6}{str(r['mcap_med']):>9}{str(r['sol_med']):>6}{r['buys_h']:>5}{r['last_h']:>6}")
json.dump({"all_active": out, "follow": ok}, open("state/ops/traders_v2.json", "w"), indent=1)
if len(ok) >= 5:
    json.dump({"wallets": [r["wallet"] for r in ok[:40]], "updated": time.time()}, open("state/follow_list.json", "w"), indent=1); print("follow_list actualizada:", min(40, len(ok)))
PY
