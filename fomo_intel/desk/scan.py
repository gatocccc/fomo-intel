"""Escaneo de candidatos para la mesa: tokens de Solana con liquidez real y momentum (Solana Tracker).
Filtros: liquidez >= US$150K, mcap US$1M–80M, edad >= 24 h. Imprime tabla y guarda state/desk/scan.json."""
import json, os, time, requests
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}; B = "https://data.solanatracker.io"
def get(p, **q):
    for i in range(3):
        try:
            r = requests.get(B + p, headers=H, params=q, timeout=30)
            if r.ok: return r.json()
            print("HTTP", r.status_code, p, r.text[:120])
        except Exception as e: print("err", p, e)
        time.sleep(1)
    return None
seen = {}
for p in ("/tokens/trending/1h", "/tokens/trending/6h", "/tokens/trending/24h", "/tokens/volume/24h", "/top-performers/24h", "/tokens/trending"):
    d = get(p)
    rows = d if isinstance(d, list) else (d or {}).get("tokens") or (d or {}).get("data") or []
    print(p, len(rows))
    for x in rows:
        t = x.get("token") or {}; m = t.get("mint")
        if not m: continue
        pools = x.get("pools") or []
        pl = max(pools, key=lambda q: ((q.get("liquidity") or {}).get("usd") or 0), default={})
        ev = x.get("events") or {}
        created = min([(q.get("createdAt") or 9e15) for q in pools] or [9e15]) / 1000
        r = x.get("risk") or {}
        seen.setdefault(m, {"mint": m, "sym": t.get("symbol"), "name": t.get("name"), "src": set(),
            "mcap": (pl.get("marketCap") or {}).get("usd") or 0, "liq": (pl.get("liquidity") or {}).get("usd") or 0,
            "age_d": round((time.time() - created) / 86400, 1) if created < 9e12 else None, "market": pl.get("market"),
            "ch1h": (ev.get("1h") or {}).get("priceChangePercentage"), "ch6h": (ev.get("6h") or {}).get("priceChangePercentage"),
            "ch24h": (ev.get("24h") or {}).get("priceChangePercentage"), "holders": x.get("holders"),
            "risk": r.get("score"), "top10": r.get("top10"), "rugged": r.get("rugged"),
            "buys": x.get("buys"), "sells": x.get("sells"), "txns": x.get("txns"),
            "tw": t.get("twitter") or (t.get("strictSocials") or {}).get("twitter"), "desc": (t.get("description") or "")[:120]})["src"].add(p.split("/")[-1])
c = [v for v in seen.values() if v["liq"] >= 150_000 and 1e6 <= v["mcap"] <= 8e7 and (v["age_d"] or 0) >= 1 and not v["rugged"]]
c.sort(key=lambda v: -(v["ch24h"] or 0))
print(f"\ncandidatos: {len(c)} de {len(seen)}")
f = lambda v: "—" if v is None else f"{v:+.0f}%"
for v in c[:45]:
    print(f"{v['sym'][:12]:12s} mcap ${v['mcap']/1e6:6.1f}M liq ${v['liq']/1e3:5.0f}K edad {v['age_d']:5}d 1h {f(v['ch1h']):>6} 6h {f(v['ch6h']):>6} 24h {f(v['ch24h']):>7} hold {v['holders']} risk {v['risk']} top10 {round(v['top10'] or 0)}% {v['market']} {','.join(sorted(v['src']))} | {v['mint']} | {(v['tw'] or '')[:40]} | {v['desc'][:60]}")
for v in seen.values(): v["src"] = sorted(v["src"])
json.dump({"ts": time.time(), "cands": c, "all": list(seen.values())}, open("state/desk/scan.json", "w"))
