"""Escaneo con detector de volumen fabricado: candidatos con volumen REAL (irregular, alto respecto de la mcap).
Para cada token de los rankings con liquidez >= 150K y mcap 2–200M: velas 1h de 48 h -> volumen 24h, coeficiente de variación del volumen
por hora (CV bajo = bot), volumen/mcap, cambio 24h/72h, distancia al máximo de 7 días."""
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
for p in ("/tokens/volume/24h", "/tokens/volume/6h", "/tokens/volume/1h", "/tokens/trending/24h", "/tokens/trending/6h", "/top-performers/24h", "/top-performers/6h", "/tokens/graduated"):
    d = get(p); rows = d if isinstance(d, list) else (d or {}).get("tokens") or (d or {}).get("data") or []
    for x in rows:
        t = x.get("token") or {}; m = t.get("mint")
        if not m or m in seen: continue
        pools = x.get("pools") or []
        pl = max(pools, key=lambda q: ((q.get("liquidity") or {}).get("usd") or 0), default={})
        seen[m] = {"mint": m, "sym": t.get("symbol"), "mcap": (pl.get("marketCap") or {}).get("usd") or 0, "liq": (pl.get("liquidity") or {}).get("usd") or 0,
                   "holders": x.get("holders"), "top10": (x.get("risk") or {}).get("top10"), "tw": t.get("twitter") or "", "desc": (t.get("description") or "")[:80]}
print("tokens en rankings:", len(seen))
now = int(time.time()); out = []
STABLE = {"USDC", "USDT", "SOL", "WSOL", "JUP", "JitoSOL", "mSOL", "bSOL", "USD1", "PYUSD", "USDS"}
for v in seen.values():
    if v["liq"] < 150_000 or not (2e6 <= v["mcap"] <= 2e8) or (v["sym"] or "") in STABLE: continue
    cs = (get(f"/chart/{v['mint']}", type="1h", time_from=now - 7 * 86400, time_to=now) or {}).get("oclhv", [])
    if len(cs) < 30: continue
    vol = [float(c.get("volume") or 0) for c in cs]; cl = [float(c["close"]) for c in cs]; hi = max(float(c["high"]) for c in cs)
    v24 = sum(vol[-24:]); cv = st.pstdev(vol[-24:]) / (st.mean(vol[-24:]) or 1)
    v.update({"vol24": v24, "vol_mcap": v24 / v["mcap"], "cv": cv, "ch24": cl[-1] / cl[-25] - 1, "ch72": cl[-1] / cl[-73] - 1 if len(cl) > 73 else None,
              "from_hi": cl[-1] / hi, "ch6": cl[-1] / cl[-7] - 1})
    out.append(v)
real = [v for v in out if v["cv"] >= 0.45 and v["vol_mcap"] >= 0.15]
fake = [v for v in out if v["cv"] < 0.3]
print(f"con velas: {len(out)} | volumen con patrón de bot (CV<0,3): {len(fake)} -> {[v['sym'] for v in fake]}")
print(f"volumen real y alto (CV>=0,45, vol/mcap>=15%): {len(real)}\n")
real.sort(key=lambda v: -v["ch24"])
for v in real:
    print(f"{(v['sym'] or '')[:10]:10s} mcap ${v['mcap']/1e6:6.1f}M liq ${v['liq']/1e3:5.0f}K vol24 ${v['vol24']/1e6:5.2f}M ({v['vol_mcap']:.0%}) CV {v['cv']:.2f} | 6h {v['ch6']:+.0%} 24h {v['ch24']:+.0%} 72h {(v['ch72'] or 0):+.0%} | {v['from_hi']:.0%} del máx 7d | hold {v['holders']} top10 {round(v['top10'] or 0)}% | {v['mint']} | {v['tw'][:45]} {v['desc'][:50]}")
json.dump({"ts": time.time(), "real": real, "all": out}, open("state/desk/scan2.json", "w"))
