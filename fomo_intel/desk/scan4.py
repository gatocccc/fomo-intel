"""Escaneo amplio (28/10): rankings + /search de Solana Tracker por rango de mcap (US$300K–30M).
Filtros de la mesa: liquidez >= US$150K, edad >= 24 h, CV volumen horario >= 0,45, vol 24 h >= 15% mcap, top10 < 30%.
Imprime candidatos y deja las mints en state/desk/scan4_top.txt para el chequeo anti-rug."""
import json, os, statistics as st, time, requests
# parámetros (desde 28/10 noche también para el plan agresivo "rápido": SCAN_LO=3e5 SCAN_HI=3e6 SCAN_LIQ=6e4 SCAN_AGE_H=6 SCAN_OUT=state/desk/scan_fast.json)
E = lambda k, d: float(os.environ.get(k, d))
LO, HI, LIQ, AGE_H = E("SCAN_LO", 3e5), E("SCAN_HI", 3e7), E("SCAN_LIQ", 150000), E("SCAN_AGE_H", 24)
VOLMCAP, TOP10, MINC = E("SCAN_VOLMCAP", 0.15), E("SCAN_TOP10", 30), int(E("SCAN_MIN_CANDLES", 24))
OUT = os.environ.get("SCAN_OUT", "state/desk/scan4.json")
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}; B = "https://data.solanatracker.io"
def get(p, **q):
    for i in range(3):
        try:
            r = requests.get(B + p, headers=H, params=q, timeout=30)
            if r.ok: return r.json()
            if i == 0: print("  http", r.status_code, p, str(q)[:80], r.text[:120])
        except Exception as e: print("  err", p, e)
        time.sleep(1.2)
    return None
seen = {}
def add_rank(x):
    t = x.get("token") or {}; m = t.get("mint")
    if not m or m in seen: return
    pools = x.get("pools") or []
    pl = max(pools, key=lambda q: ((q.get("liquidity") or {}).get("usd") or 0), default={})
    created = min([(q.get("createdAt") or 9e15) for q in pools] or [9e15]) / 1000
    r = x.get("risk") or {}
    seen[m] = {"mint": m, "sym": t.get("symbol"), "mcap": (pl.get("marketCap") or {}).get("usd") or 0, "liq": (pl.get("liquidity") or {}).get("usd") or 0,
               "created": created if created < 9e12 else None, "holders": x.get("holders"), "top10": r.get("top10"), "rugged": r.get("rugged"),
               "tw": t.get("twitter") or "", "desc": (t.get("description") or "")[:60], "src": "rank"}
for p in ("/tokens/volume/1h", "/tokens/volume/6h", "/tokens/volume/24h", "/tokens/trending/1h", "/tokens/trending/6h", "/tokens/trending/24h",
          "/top-performers/1h", "/top-performers/6h", "/top-performers/24h", "/tokens/graduated", "/tokens/latest"):
    d = get(p); rows = d if isinstance(d, list) else (d or {}).get("tokens") or (d or {}).get("data") or []
    for x in rows: add_rank(x)
print("en rankings:", len(seen))
n0 = len(seen); shown = False
bands = [(a, b) for a, b in ((3e5, 1e6), (1e6, 3e6), (3e6, 1e7), (1e7, 3e7)) if b > LO and a < HI]
for lo, hi in bands:
    for sort in ("volume_24h", "volume", "createdAt"):
        for page in (1, 2):
            d = get("/search", query="", minMarketCap=int(lo), maxMarketCap=int(hi), minLiquidity=int(LIQ), sortBy=sort, sortOrder="desc", limit=100, page=page)
            rows = (d or {}).get("data") or []
            if rows and not shown: print("  campos /search:", sorted(rows[0].keys())[:40]); shown = True
            for x in rows:
                m = x.get("mint")
                if not m or m in seen: continue
                ca = x.get("createdAt") or x.get("created_at") or 0
                ca = ca / 1000 if ca and ca > 1e12 else ca
                seen[m] = {"mint": m, "sym": x.get("symbol"), "mcap": x.get("marketCapUsd") or x.get("marketCap") or 0, "liq": x.get("liquidityUsd") or x.get("liquidity") or 0,
                           "created": ca or None, "holders": x.get("holders"), "top10": (x.get("top10") if x.get("top10") is not None else None), "rugged": x.get("rugged"),
                           "tw": x.get("twitter") or "", "desc": "", "src": "search"}
            if len(rows) < 100: break
        if any(v["src"] == "search" for v in seen.values()): pass
print("sumados por /search:", len(seen) - n0, "| total:", len(seen))
now = int(time.time()); out = []
pre = [v for v in seen.values() if (v["liq"] or 0) >= LIQ and LO <= (v["mcap"] or 0) <= HI and not v["rugged"]
       and v["created"] and (now - v["created"]) / 3600 >= AGE_H]
print("pasan liquidez/mcap/edad:", len(pre))
for v in pre[:160]:
    cs = (get(f"/chart/{v['mint']}", type="1h", time_from=now - 72 * 3600, time_to=now) or {}).get("oclhv", [])
    if len(cs) < MINC: continue
    vol = [float(c.get("volume") or 0) for c in cs]; cl = [float(c["close"]) for c in cs]; hi = max(float(c["high"]) for c in cs[-72:])
    w = min(24, len(vol)); v24 = sum(vol[-w:]) * 24 / w; cv = st.pstdev(vol[-w:]) / (st.mean(vol[-w:]) or 1); v6 = sum(vol[-6:])
    v.update({"age_h": round((now - v["created"]) / 3600), "vol24": v24, "vol_mcap": v24 / v["mcap"], "cv": cv, "accel": (v6 / 6) / (v24 / 24) if v24 else 0,
              "ch1h": cl[-1] / cl[-2] - 1, "ch6h": cl[-1] / cl[-7] - 1 if len(cl) > 7 else cl[-1] / cl[0] - 1, "ch24h": cl[-1] / cl[-25] - 1 if len(cl) > 25 else cl[-1] / cl[0] - 1,
              "ch72h": cl[-1] / cl[0] - 1, "from_hi": cl[-1] / hi})
    out.append(v)
print("con velas:", len(out))
need_top = [v for v in out if v["cv"] >= 0.45 and v["vol_mcap"] >= VOLMCAP and v["top10"] is None]
for v in need_top[:40]:
    d = get(f"/tokens/{v['mint']}") or {}
    r = d.get("risk") or {}; v["top10"] = r.get("top10"); v["holders"] = v["holders"] or d.get("holders")
    v["bund"] = (r.get("bundlers") or {}).get("totalPercentage") if isinstance(r.get("bundlers"), dict) else None
    tk = d.get("token") or {}; v["tw"] = v["tw"] or tk.get("twitter") or ""; v["desc"] = (tk.get("description") or "")[:60]
ok = [v for v in out if v["cv"] >= 0.45 and v["vol_mcap"] >= VOLMCAP and v["top10"] is not None and v["top10"] < TOP10]
# preferimos: retroceso (no comprar la vela de euforia), volumen acelerando, tendencia de 72 h positiva
for v in ok: v["score"] = v["accel"] * min(v["vol_mcap"], 3) * (1 + max(min(v["ch72h"], 3), -0.5)) * (1.3 if 0.55 <= v["from_hi"] <= 0.9 else 1) * (0.5 if v["ch24h"] > 2 else 1)
ok.sort(key=lambda v: -v["score"])
print(f"PASAN TODOS LOS FILTROS: {len(ok)}\n")
for v in ok[:25]:
    print(f"{(v['sym'] or '')[:10]:10s} mcap ${v['mcap']/1e6:5.2f}M liq ${v['liq']/1e3:4.0f}K edad {v['age_h']:4d}h vol24 ${v['vol24']/1e3:6.0f}K ({v['vol_mcap']:.2f}x) acel {v['accel']:.1f} CV {v['cv']:.2f} | 1h {v['ch1h']:+.0%} 6h {v['ch6h']:+.0%} 24h {v['ch24h']:+.0%} 72h {v['ch72h']:+.0%} | {v['from_hi']:.0%} del máx | hold {v['holders']} top10 {round(v['top10'])}% | {v['mint']} | {v['tw'][:35]} {v['desc'][:40]}")
os.makedirs("state/desk", exist_ok=True)
json.dump({"ts": time.time(), "ok": ok, "all": out}, open(OUT, "w"))
if OUT.endswith("scan4.json"): open("state/desk/scan4_top.txt", "w").write(" ".join(v["mint"] for v in ok[:5]))
