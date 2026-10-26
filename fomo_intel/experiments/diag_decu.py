"""Diagnóstico: ¿por qué Helius no ve compras/ventas de decu? Muestra sus últimos trades (ST) y una muestra de avisos de Helius."""
import json, os, time, collections, requests, websocket
W = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"
H = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
d = requests.get(f"https://data.solanatracker.io/wallet/{W}/trades", headers=H, timeout=30).json()
tr = d.get("trades", [])
now = time.time()
print("últimos trades ST (hace cuántos min):", [round((now - t["time"] / 1000) / 60, 1) for t in tr[:15]])
hrs = collections.Counter(time.strftime("%H", time.gmtime(t["time"] / 1000)) for t in tr)
print("trades por hora UTC (última página):", sorted(hrs.items()))
for t in tr[:3]:
    print("TX", t.get("tx"), t.get("program"), (t.get("from") or {}).get("token", {}).get("symbol"), "->", (t.get("to") or {}).get("token", {}).get("symbol"))
key = os.environ["HELIUS_API_KEY"]
ws = websocket.create_connection(f"wss://mainnet.helius-rpc.com/?api-key={key}", timeout=10)
ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [W]}, {"commitment": "processed"}]}))
t0, n, err, progs, samples, sigs = time.time(), 0, 0, collections.Counter(), [], []
while time.time() - t0 < 60:
    try: m = json.loads(ws.recv())
    except Exception: continue
    if m.get("method") != "logsNotification": continue
    v = m["params"]["result"]["value"]; n += 1
    if v.get("err"): err += 1
    lg = v.get("logs") or []
    for l in lg:
        if l.startswith("Program ") and " invoke [1]" in l: progs[l.split()[1]] += 1
    if len(samples) < 4 and not v.get("err"): samples.append(lg[:12]); sigs.append(v.get("signature"))
print(f"avisos en 60 s: {n}, con error: {err}")
print("programas de nivel 1:", progs.most_common(10))
for s, lg in zip(sigs, samples): print("SIG", s); print("   " + "\n   ".join(lg))
rpc = f"https://mainnet.helius-rpc.com/?api-key={key}"
for s in sigs[:2]:
    r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]}).json().get("result") or {}
    msg = (r.get("transaction") or {}).get("message", {})
    print("TX", s[:10], "firmantes:", [k["pubkey"][:8] for k in msg.get("accountKeys", []) if k.get("signer")])
