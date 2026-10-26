"""Auditoría de billeteras (tweet GMB_XBT 25/10): PnL, ganancia por dólar, tenencia, tamaño, capitalización."""
import os, sys, json, time, statistics as st, requests
BASE = "https://data.solanatracker.io"
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
SOL = "So11111111111111111111111111111111111111112"
W = {"decu": "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9",
     "zeropnl_wugi": "4xY9T1Q7foJzJsJ6YZDSsfp9zkzeZsXnxd45SixduMmr",
     "sheep": "78N177fzNJpp8pG49xDv1efYcTMSzo9tPTKEA9mAVkh2"}

def get(path, **p):
    for i in range(3):
        try:
            r = requests.get(BASE + path, headers=H, params=p, timeout=30)
            if r.status_code == 200: return r.json()
            print("  HTTP", r.status_code, path, r.text[:200])
        except Exception as e: print("  err", e)
        time.sleep(2)
    return None

def q(v, k): return [x for x in v if x is not None][k] if v else None
def pct(v, k):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v)-1, int(len(v)*k))], 2) if v else None

for name, w in W.items():
    print(f"\n===== {name} {w}")
    s = get(f"/pnl/{w}", showHistoricPnL="true")
    if s:
        summ = s.get("summary", s)
        print("SUMMARY", json.dumps({k: summ.get(k) for k in summ if not isinstance(summ.get(k), (dict, list))})[:1500])
        hist = s.get("historic") or summ.get("historic")
        if hist: print("HISTORIC", json.dumps(hist)[:800])
        toks = s.get("tokens") or {}
        print("tokens en pnl:", len(toks))
    trades, cursor, now = [], None, time.time()
    for page in range(40):
        p = {"cursor": cursor} if cursor else {}
        d = get(f"/wallet/{w}/trades", **p)
        if not d: break
        t = d.get("trades", [])
        trades += t
        cursor = d.get("nextCursor")
        if not t or not cursor or (now - (t[-1].get("time", 0) / 1000)) > 3 * 86400: break
    print("trades bajados:", len(trades))
    if trades: print("EJEMPLO", json.dumps(trades[0])[:900])
    pos, sizes = {}, []
    for t in trades:
        ts = t.get("time", 0) / 1000
        fr, to = t.get("from", {}), t.get("to", {})
        vol = (t.get("volume") or {}).get("usd")
        if to.get("address") and to.get("address") != SOL and fr.get("address") == SOL:
            mint, side = to["address"], "buy"
        elif fr.get("address") and fr.get("address") != SOL and to.get("address") == SOL:
            mint, side = fr["address"], "sell"
        else: continue
        p = pos.setdefault(mint, {"buys": [], "sells": [], "bu": 0, "su": 0, "sym": (to if side == "buy" else fr).get("token", {}).get("symbol")})
        p[side + "s"].append(ts); p["bu" if side == "buy" else "su"] += vol or 0
        if side == "buy" and vol: sizes.append(vol)
    holds, rets = [], []
    for m, p in pos.items():
        if p["buys"] and p["sells"]:
            holds.append((max(p["sells"]) - min(p["buys"])) / 60)
            if p["bu"] > 0: rets.append(p["su"] / p["bu"] - 1)
    print(f"tokens operados (3d): {len(pos)} | completos: {len(holds)}")
    print(f"tamaño compra US$: mediana {pct(sizes,.5)} p25 {pct(sizes,.25)} p75 {pct(sizes,.75)}")
    print(f"tenencia min: p25 {pct(holds,.25)} mediana {pct(holds,.5)} p75 {pct(holds,.75)} | <1min {sum(h<1 for h in holds)} <5min {sum(h<5 for h in holds)} >60min {sum(h>60 for h in holds)}")
    if rets:
        print(f"retorno por token: acierto {sum(r>0 for r in rets)/len(rets):.0%} mediana {pct(rets,.5)} media {round(st.mean(rets),3)}")
        tb, ts_ = sum(p['bu'] for p in pos.values() if p['sells']), sum(p['su'] for p in pos.values() if p['buys'])
        print(f"ganancia por dólar (tokens completos 3d): {(ts_/tb-1) if tb else None:.3f} sobre US${tb:,.0f}")
    # capitalización de 8 tokens más recientes comprados
    recent = sorted(pos.items(), key=lambda kv: -max(kv[1]["buys"] or [0]))[:8]
    for m, p in recent:
        ti = get(f"/tokens/{m}")
        mc = liq = None; created = None
        if ti:
            pools = ti.get("pools") or []
            if pools:
                mc = (pools[0].get("marketCap") or {}).get("usd"); liq = (pools[0].get("liquidity") or {}).get("usd")
                created = pools[0].get("createdAt")
        age = round((min(p["buys"]) - created/1000)/60, 1) if created and p["buys"] else None
        print(f"  {p['sym']}: mcap_actual {mc} liq {liq} | compró a los {age} min de creado | buy US${p['bu']:.0f} sell US${p['su']:.0f}")
