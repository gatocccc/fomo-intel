"""Baja datos históricos para el backtest de majors (30/10). Imprime un JSON gzip+base64 entre marcas para que la sesión lo lea.
Fuentes: Binance (data-api.binance.vision, sin clave), Hyperliquid (velas 1h y funding), Stooq/Yahoo (acciones)."""
import base64, gzip, json, sys, time
import requests
OUT = {}
def get(u, **kw):
    for i in range(4):
        try:
            r = requests.get(u, timeout=30, **kw)
            if r.status_code == 200: return r
        except Exception as e: print("err", u[:80], e, file=sys.stderr)
        time.sleep(1 + i)
    return None
def binance(sym, itv, start_ms):
    rows = []; t = start_ms
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        rows = []; t = start_ms
        while True:
            r = get(f"{host}/api/v3/klines", params={"symbol": sym, "interval": itv, "startTime": t, "limit": 1000})
            if not r: break
            k = r.json()
            if not k: break
            rows += [[int(x[0] // 1000), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[7])] for x in k]
            if len(k) < 1000: break
            t = k[-1][0] + 1
        if rows: break
    return rows
start = int(time.mktime((2020, 1, 1, 0, 0, 0, 0, 0, 0)) * 1000)
for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT"]:
    OUT[f"{s}_1d"] = binance(s, "1d", start)
    OUT[f"{s}_4h"] = binance(s, "4h", start)
    OUT[f"{s}_1h"] = binance(s, "1h", int((time.time() - 90 * 86400) * 1000))
    print(s, len(OUT[f"{s}_1d"]), len(OUT[f"{s}_4h"]), len(OUT[f"{s}_1h"]), file=sys.stderr)
# funding Hyperliquid (8 meses, de a 500 filas)
for c in ["BTC", "ETH", "SOL"]:
    rows = []; t = int((time.time() - 240 * 86400) * 1000)
    while True:
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "fundingHistory", "coin": c, "startTime": t}, timeout=30).json()
        except Exception: break
        if not r: break
        rows += [[int(x["time"] // 1000), float(x["fundingRate"])] for x in r]
        if len(r) < 500: break
        t = r[-1]["time"] + 1
    OUT[f"HL_funding_{c}"] = rows; print("funding", c, len(rows), file=sys.stderr)
# acciones (diario)
for tk in ["SPY", "QQQ", "NVDA", "TSLA", "COIN", "MSTR", "AAPL", "GLD"]:
    rows = []
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}", params={"range": "10y", "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"})
    try:
        j = r.json()["chart"]["result"][0]; q = j["indicators"]["quote"][0]
        rows = [[t, o, h, l, c, v] for t, o, h, l, c, v in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]) if c]
    except Exception:
        r = get(f"https://stooq.com/q/d/l/?s={tk.lower()}.us&i=d")
        if r and "Date" in r.text[:20]:
            for ln in r.text.splitlines()[1:]:
                p = ln.split(",")
                try: rows.append([int(time.mktime(time.strptime(p[0], "%Y-%m-%d"))), *map(float, p[1:6])])
                except Exception: pass
    OUT[f"STK_{tk}"] = rows; print("stock", tk, len(rows), file=sys.stderr)
blob = base64.b64encode(gzip.compress(json.dumps(OUT).encode())).decode()
print("===DATA==="); print(blob); print("===END===")
