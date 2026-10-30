"""Due diligence anti-rug para la mesa: fondeador común de los top holders + historial del creador.

Uso: python -m fomo_intel.desk.dd MINT [MINT ...]
Salida legible + JSON en state/desk/dd/<mint>.json.
"""
import json, os, sys, time
from collections import defaultdict
import requests

ST = "https://data.solanatracker.io"
STH = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
HK = os.environ.get("HELIUS_API_KEY", "")
RPC = os.environ.get("SOLANA_RPC_URL") or f"https://mainnet.helius-rpc.com/?api-key={HK}"
SYSTEM = "11111111111111111111111111111111"
TOP_N = 20



# Fondeadores que son hot wallets de exchanges y que la vía RPC devuelve sin etiqueta.
# 5tzFkiKs… (Binance) disparó CONCENTRADO falso en STONK (28/10 y 29/10) y en JOB (29/10) por "grupo de ≥4 billeteras".
KNOWN_CEX = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance hot wallet",
}

def st(path, **p):
    for i in range(3):
        try:
            r = requests.get(ST + path, headers=STH, params=p, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + i)
    return None


RPC_FALLBACK = "https://api.mainnet-beta.solana.com"


_HELIUS_DOWN = {"rpc": False, "api": False}


def rpc(method, params):
    # 30/10: Helius llegó a su tope de uso ("max usage reached", 429) y el anti-rug entero colgaba o caía con JSONDecodeError
    # (ops 167–169). Ahora: si Helius responde 429 una vez, el resto de la corrida usa la RPC pública de Solana.
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    urls = [RPC_FALLBACK, RPC_FALLBACK] if _HELIUS_DOWN["rpc"] else [RPC, RPC, RPC_FALLBACK, RPC_FALLBACK]
    for i, url in enumerate(urls):
        try:
            r = requests.post(url, json=body, timeout=20)
            if r.status_code == 200:
                return r.json().get("result")
            if r.status_code == 429 and url == RPC:
                _HELIUS_DOWN["rpc"] = True
        except Exception:
            pass
        time.sleep(1.0 * (i + 1))
    return None


def is_wallet(addrs):
    """True si la cuenta es una billetera común (dueña: System Program). Pools/curvas son de programas."""
    out = {}
    for i in range(0, len(addrs), 100):
        chunk = addrs[i:i + 100]
        res = rpc("getMultipleAccounts", [chunk, {"encoding": "base64"}]) or {}
        for a, acc in zip(chunk, res.get("value") or []):
            out[a] = acc is None or acc.get("owner") == SYSTEM
    return out


def funder_helius(addr):
    if _HELIUS_DOWN["api"]:
        return None
    try:
        r = requests.get(f"https://api.helius.xyz/v1/wallet/{addr}/funded-by", params={"api-key": HK}, timeout=20)
        if r.status_code == 429:
            _HELIUS_DOWN["api"] = True
        if r.status_code == 200:
            j = r.json()
            f = j.get("funder") or j.get("funderAddress") or j.get("address")
            if f:
                return {"funder": f, "name": j.get("funderName") or j.get("name"), "type": j.get("funderType") or j.get("type"), "src": "helius"}
    except Exception:
        pass
    return None


def funder_rpc(addr, max_pages=3):
    """Respaldo: primera transacción de la billetera y quién le mandó SOL."""
    before, oldest = None, None
    for _ in range(max_pages):
        p = {"limit": 1000}
        if before:
            p["before"] = before
        sigs = rpc("getSignaturesForAddress", [addr, p]) or []
        if not sigs:
            break
        oldest = sigs[-1]["signature"]; before = oldest
        if len(sigs) < 1000:
            break
    else:
        return {"funder": None, "src": "rpc", "note": "historia muy larga"}
    if not oldest:
        return None
    tx = rpc("getTransaction", [oldest, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
    if not tx:
        return None
    for ins in (tx.get("transaction", {}).get("message", {}).get("instructions") or []):
        pr = ins.get("parsed") or {}
        if isinstance(pr, dict) and pr.get("type") in ("transfer", "createAccount") and (pr.get("info") or {}).get("destination", (pr.get("info") or {}).get("newAccount")) == addr:
            return {"funder": pr["info"].get("source"), "src": "rpc"}
    keys = tx.get("transaction", {}).get("message", {}).get("accountKeys") or []
    payer = keys[0].get("pubkey") if keys and isinstance(keys[0], dict) else (keys[0] if keys else None)
    return {"funder": payer if payer != addr else None, "src": "rpc-payer"}


def holders_top(mint):
    h = st(f"/tokens/{mint}/holders/top") or []
    lst = h if isinstance(h, list) else h.get("holders", h.get("accounts", []))
    out = []
    for x in lst[:TOP_N]:
        a = x.get("address") or x.get("wallet") or x.get("owner")
        if a:
            out.append({"address": a, "pct": float(x.get("percentage") or 0)})
    return out


def deployer_history(creator):
    if not creator:
        return None
    d = st(f"/deployer/{creator}") or {}
    toks = d.get("tokens") or d.get("data") or (d if isinstance(d, list) else [])
    total = d.get("total") or len(toks)
    dead = grad = 0
    for t in toks:
        tk = t.get("token", t)
        mc = None
        for p in (t.get("pools") or []):
            mc = max(mc or 0, float((p.get("marketCap") or {}).get("usd") or 0))
        if mc is None:
            mc = float(t.get("marketCapUsd") or t.get("marketCap") or 0)
        if mc and mc < 10_000:
            dead += 1
        if any((p.get("market") or "") not in ("pumpfun", "pumpfun-amm-curve", "") and "curve" not in (p.get("market") or "") for p in (t.get("pools") or [])):
            grad += 1
    return {"creator": creator, "lanzamientos": total, "muertos_<US$10K": dead, "graduados_aprox": grad, "muestra": len(toks)}


def analyze(mint):
    info = st(f"/tokens/{mint}") or {}
    tk = info.get("token", {}); risk = info.get("risk", {})
    sym = tk.get("symbol") or mint[:6]
    creator = (tk.get("creation") or {}).get("creator") or tk.get("creator")
    hs = holders_top(mint)
    wal = is_wallet([h["address"] for h in hs])
    wallets = [h for h in hs if wal.get(h["address"], True)]
    pools = [h for h in hs if not wal.get(h["address"], True)]
    for h in wallets:
        # con Helius en tope de uso, el respaldo por RPC pública tarda >9 min por token (ops 170) y trababa al cerebro: se salta → SIN_DATOS
        f = funder_helius(h["address"]) or ({} if _HELIUS_DOWN["api"] else funder_rpc(h["address"])) or {}
        h.update({k: v for k, v in f.items()})
        time.sleep(0.15)
    groups = defaultdict(list)
    for h in wallets:
        if h.get("funder"):
            groups[h["funder"]].append(h)
    clusters = []
    for f, mem in groups.items():
        if len(mem) >= 2:
            label = mem[0].get("name") or ""
            typ = (mem[0].get("type") or "").lower()
            cex = f in KNOWN_CEX or any(w in (label + typ).lower() for w in ("exchange", "binance", "coinbase", "okx", "bybit", "kraken", "kucoin", "mexc", "gate", "bitget", "cex"))
            if f in KNOWN_CEX and not label:
                label = KNOWN_CEX[f]
            clusters.append({"funder": f, "label": label, "cex": cex, "n": len(mem), "pct": round(sum(m["pct"] for m in mem), 2), "wallets": [m["address"] for m in mem]})
    clusters.sort(key=lambda c: -c["pct"])
    funded_by_creator = [h for h in wallets if creator and h.get("funder") == creator]
    sus = [c for c in clusters if not c["cex"]]
    sus_pct = round(sum(c["pct"] for c in sus), 2)
    dev = deployer_history(creator)
    if sus_pct >= 10 or any(c["n"] >= 4 for c in sus) or funded_by_creator:
        verdict = "CONCENTRADO"
    elif sus_pct >= 5:
        verdict = "VIGILAR"
    else:
        verdict = "LIMPIO"
    # 30/10: sin datos no hay LIMPIO. Si no se pudo identificar el fondeador de la mitad o más de los holders (API caída,
    # sin claves, tope de uso), el veredicto es SIN_DATOS y el cerebro no compra (exige LIMPIO).
    if verdict == "LIMPIO" and (not wallets or sum(1 for h in wallets if not h.get("funder")) * 2 >= len(wallets)):
        verdict = "SIN_DATOS"
    res = {"mint": mint, "symbol": sym, "ts": int(time.time()), "verdict": verdict,
           "top_wallets_pct": round(sum(h["pct"] for h in wallets), 2), "pools_pct": round(sum(h["pct"] for h in pools), 2),
           "clusters_sospechosos_pct": sus_pct, "clusters": clusters,
           "fondeados_por_creador": [(h["address"], h["pct"]) for h in funded_by_creator],
           "sin_fondeador": sum(1 for h in wallets if not h.get("funder")),
           "risk": {"bundlers%": (risk.get("bundlers") or {}).get("totalPercentage"), "insiders%": (risk.get("insiders") or {}).get("totalPercentage"),
                    "snipers%": (risk.get("snipers") or {}).get("totalPercentage"), "dev%": (risk.get("dev") or {}).get("percentage"),
                    "risks": [x.get("name") for x in risk.get("risks", [])]},
           "deployer": dev, "holders": wallets}
    os.makedirs("state/desk/dd", exist_ok=True)
    json.dump(res, open(f"state/desk/dd/{mint}.json", "w"), indent=1)
    return res


def show(r):
    print(f"\n=== {r['symbol']} {r['mint']} → {r['verdict']}")
    print(f"top {TOP_N}: billeteras {r['top_wallets_pct']}% · pools/curva {r['pools_pct']}% · sin fondeador identificado {r['sin_fondeador']}")
    print("riesgo ST:", r["risk"])
    print("creador:", r["deployer"])
    if r["fondeados_por_creador"]:
        print("!! holders fondeados por el CREADOR:", r["fondeados_por_creador"])
    if not r["clusters"]:
        print("sin grupos con fondeador común")
    for c in r["clusters"]:
        print(f"  grupo fondeador {c['funder'][:8]}… {c['label'] or ''} {'(exchange)' if c['cex'] else ''}: {c['n']} billeteras, {c['pct']}%")
    print("detalle:", [(h["address"][:6], round(h["pct"], 2), (h.get("funder") or "?")[:6], h.get("src")) for h in r["holders"]])


if __name__ == "__main__":
    for m in sys.argv[1:]:
        try:
            show(analyze(m))
        except Exception as e:
            print("ERROR", m, repr(e))
