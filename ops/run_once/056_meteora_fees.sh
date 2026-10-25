#!/bin/bash
# Datos reales de Meteora DLMM: comisiones generadas por pools de memecoins vs liquidez (rendimiento bruto de proveer liquidez).
cd /root/fomo_intel
timeout 200 python3 -u - <<'PY'
import requests, json, statistics as st
urls = ["https://dlmm-api.meteora.ag/pair/all_with_pagination?page=0&limit=100&sort_key=volume&order_by=desc",
        "https://dlmm-api.meteora.ag/pair/all_by_groups?sort_key=volume&order_by=desc&limit=100"]
pairs = []
for u in urls:
    try:
        r = requests.get(u, timeout=40); print(u.split("?")[0], r.status_code, len(r.text))
        j = r.json(); pairs = j.get("pairs") or j.get("data") or (j if isinstance(j, list) else [])
        if pairs: break
    except Exception as e: print("error", e)
if not pairs: raise SystemExit("sin datos")
print("campos:", sorted(pairs[0].keys())[:40])
rows = []
for p in pairs:
    name = p.get("name") or ""; liq = float(p.get("liquidity") or 0); f24 = float((p.get("fees_24h") or 0)); v24 = float(p.get("trade_volume_24h") or 0)
    if liq < 20000: continue
    if any(x in name.upper() for x in ("USDC-USDT", "USDT-USDC", "SOL-USDC", "USDC-SOL", "JITOSOL", "MSOL", "JUPSOL", "BSOL", "CBBTC", "WBTC", "ETH-")): continue
    rows.append({"name": name, "liq": liq, "fees24": f24, "vol24": v24, "apr_dia": f24/liq*100, "bin": p.get("bin_step"), "fee_pct": p.get("base_fee_percentage")})
rows.sort(key=lambda r: -r["vol24"])
print(f"\npools no-estables con liquidez >= US$20K: {len(rows)}")
print(f"comisión diaria / liquidez: mediana {st.median(r['apr_dia'] for r in rows):.2f}% por día ; p75 {sorted(r['apr_dia'] for r in rows)[3*len(rows)//4]:.2f}%")
for r in rows[:30]: print(f"  {r['name'][:22]:<22} liq US${r['liq']:>11,.0f} vol24 US${r['vol24']:>12,.0f} comisiones24 US${r['fees24']:>9,.0f} = {r['apr_dia']:5.2f}%/día  bin {r['bin']} fee {r['fee_pct']}%")
PY
