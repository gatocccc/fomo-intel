"""Escaneo agresivo: tokens chicos (mcap US$300K–3M), edad 6 h–10 días, liquidez >= US$60K, volumen real alto. Velas de 15 min de 48 h."""
import json, os, statistics as st, time, requests
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}; B = "https://data.solanatracker.io"
def get(p, **q):
    for i in range(3):
        try:
            r = requests.get(B + p, headers=H, params=q, timeout=30)
            if r.ok: return r.json()
        except Exception: pass
        time.sleep(1)
    return None
seen = {}
for p in ("/tokens/volume/1h", "/tokens/volume/6h", "/tokens/volume/24h", "/tokens/trending/1h", "/tokens/trending/6h", "/tokens/trending/24h", "/top-performers/1h", "/top-performers/6h", "/top-performers/24h", "/tokens/graduated"):
    d = get(p); rows = d if isinstance(d, list) else (d or {}).get("tokens") or (d or {}).get("data") or []
    for x in rows:
        t = x.get("token") or {}; m = t.get("mint")
        if not m or m in seen: continue
        pools = x.get("pools") or []
        pl = max(pools, key=lambda q: ((q.get("liquidity") or {}).get("usd") or 0), default={})
        created = min([(q.get("createdAt") or 9e15) for q in pools] or [9e15]) / 1000
        r = x.get("risk") or {}
        seen[m] = {"mint": m, "sym": t.get("symbol"), "mcap": (pl.get("marketCap") or {}).get("usd") or 0, "liq": (pl.get("liquidity") or {}).get("usd") or 0,
                   "age_h": round((time.time() - created) / 3600, 1) if created < 9e12 else None, "holders": x.get("holders"), "top10": r.get("top10"),
                   "rugged": r.get("rugged"), "risk": r.get("score"), "tw": t.get("twitter") or "", "desc": (t.get("description") or "")[:70], "market": pl.get("market")}
print("en rankings:", len(seen))
now = int(time.time()); out = []
for v in seen.values():
    if v["liq"] < 60_000 or not (3e5 <= v["mcap"] <= 3e6) or v["rugged"] or not v["age_h"] or not (6 <= v["age_h"] <= 240): continue
    cs = (get(f"/chart/{v['mint']}", type="15m", time_from=now - 48 * 3600, time_to=now) or {}).get("oclhv", [])
    if len(cs) < 16: continue
    vol = [float(c.get("volume") or 0) for c in cs]; cl = [float(c["close"]) for c in cs]; hi = max(float(c["high"]) for c in cs); lo = min(float(c["low"]) for c in cs)
    v24 = sum(vol[-96:]); v6 = sum(vol[-24:]); cv = st.pstdev(vol[-24:]) / (st.mean(vol[-24:]) or 1)
    v.update({"vol24": v24, "vol6": v6, "vol_mcap": v24 / v["mcap"], "cv": cv, "ch1h": cl[-1] / cl[-5] - 1 if len(cl) > 5 else 0, "ch6h": cl[-1] / cl[-25] - 1 if len(cl) > 25 else 0,
              "ch24h": cl[-1] / cl[-97] - 1 if len(cl) > 97 else cl[-1] / cl[0] - 1, "from_hi": cl[-1] / hi, "range": hi / lo, "accel": (v6 / 6) / (v24 / 24) if v24 else 0})
    out.append(v)
ok = [v for v in out if v["cv"] >= 0.5 and v["vol_mcap"] >= 0.3 and (v["top10"] or 0) < 35]
ok.sort(key=lambda v: -(v["accel"] * (1 + v["ch6h"])))
print(f"con velas: {len(out)} | pasan (volumen real, vol/mcap>=30%, top10<35%): {len(ok)}\n")
for v in ok[:25]:
    print(f"{(v['sym'] or '')[:10]:10s} mcap ${v['mcap']/1e3:5.0f}K liq ${v['liq']/1e3:4.0f}K edad {v['age_h']:5.0f}h vol24 ${v['vol24']/1e3:5.0f}K ({v['vol_mcap']:.1f}x mcap) acel {v['accel']:.1f} CV {v['cv']:.1f} | 1h {v['ch1h']:+.0%} 6h {v['ch6h']:+.0%} 24h {v['ch24h']:+.0%} | {v['from_hi']:.0%} del máx, rango {v['range']:.1f}x | hold {v['holders']} top10 {round(v['top10'] or 0)}% | {v['mint']} | {v['tw'][:40]} {v['desc'][:45]}")
json.dump({"ts": time.time(), "ok": ok, "all": out}, open("state/desk/scan3.json", "w"))
