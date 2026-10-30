"""A/B de ruta (quote-only, sin plata): para los memecoins que operamos, ¿cuántos tokens da Solana Tracker (0,5% de comisión
por lado) vs Jupiter (sin comisión de plataforma) por el mismo SOL, en el mismo instante? Y a la vuelta, ¿cuánto SOL?
Tamaños 0,1 / 0,4 / 1,0 SOL. Resultado: diferencia en % por lado (positivo = Jupiter mejor)."""
import glob, json, os, time, requests, statistics as st
SOL = "So11111111111111111111111111111111111111112"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
JK = os.getenv("JUPITER_API_KEY", ""); JB = "https://api.jup.ag/swap/v1" if JK else "https://lite-api.jup.ag/swap/v1"
STK = os.getenv("SOLANATRACKER_API_KEY", ""); PAYER = "AXbTdJLRephZMSAMoiRwfbCBWXFYtfHeLmbPj9TZk69M"

def jq(frm, to, raw):
    for i in range(4):
        r = requests.get(f"{JB}/quote", params={"inputMint": frm, "outputMint": to, "amount": int(raw), "slippageBps": 300, "restrictIntermediateTokens": "true"},
                         headers={"x-api-key": JK} if JK else {}, timeout=15)
        if r.status_code == 429: time.sleep(1.5 * (i + 1)); continue
        return r.json() if r.status_code < 400 else None
def sq(frm, to, amt):
    r = requests.get("https://swap-v2.solanatracker.io/swap", params={"from": frm, "to": to, "fromAmount": amt, "slippage": 10, "payer": PAYER,
                     "priorityFee": 0.0005, "txVersion": "v0"}, headers={"x-api-key": STK} if STK else {}, timeout=20)
    return (r.json() or {}).get("rate") if r.status_code < 400 else None
def dec(mint):
    r = requests.post(os.getenv("RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY','')}",
                      json={"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]}, timeout=20).json()
    return r["result"]["value"]["decimals"]

mints = {}
for f in glob.glob("state/plan_*/trades.jsonl"):
    for l in open(f):
        d = json.loads(l)
        if d.get("ok") and d.get("mint") not in STABLE and d.get("symbol") not in (None, "SAFU"): mints[d["mint"]] = d["symbol"]
res = []
for m, sym in mints.items():
    try: dc = dec(m)
    except Exception as e: print(sym, "sin decimales", e); continue
    for sol in (0.1, 0.4, 1.0):
        try:
            j = jq(SOL, m, sol * 1e9); s = sq(SOL, m, sol); time.sleep(0.5)
            if not j or not s: print(sym, sol, "sin cotización", bool(j), bool(s)); continue
            jt = float(j["outAmount"]) / 10 ** dc; stt = float(s["amountOut"])
            buy_edge = (jt / stt - 1) * 100
            # vuelta: vender los tokens que daría ST
            j2 = jq(m, SOL, stt * 10 ** dc); s2 = sq(m, SOL, round(stt, dc)); time.sleep(0.5)
            sell_edge = (float(j2["outAmount"]) / 1e9 / float(s2["amountOut"]) - 1) * 100 if (j2 and s2) else None
            rt_st = (1 - float(s2["amountOut"]) / sol) * 100 if s2 else None
            rt_j = (1 - float(j2["outAmount"]) / 1e9 / sol) * 100 if j2 else None
            row = {"sym": sym, "sol": sol, "buy_jup_better_pct": round(buy_edge, 2), "sell_jup_better_pct": round(sell_edge, 2) if sell_edge is not None else None,
                   "roundtrip_cost_st_pct": round(rt_st, 2) if rt_st is not None else None, "roundtrip_cost_jup_pct": round(rt_j, 2) if rt_j is not None else None,
                   "jup_route": [r.get("swapInfo", {}).get("label") for r in j.get("routePlan") or []]}
            res.append(row); print(json.dumps(row), flush=True)
        except Exception as e: print(sym, sol, "error", str(e)[:120])
for k in ("buy_jup_better_pct", "sell_jup_better_pct", "roundtrip_cost_st_pct", "roundtrip_cost_jup_pct"):
    v = [r[k] for r in res if r.get(k) is not None]
    if v: print(k, "n", len(v), "mean", round(st.mean(v), 2), "median", round(st.median(v), 2), "min", min(v), "max", max(v))
json.dump(res, open("state/research/route_ab.json", "w"), indent=1)
