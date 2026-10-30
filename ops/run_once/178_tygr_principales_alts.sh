#!/bin/bash
# 30/10 16:45 ART — Hipótesis de Gastón: los nombres conocidos que aparecen holdeando TYGR con su cuenta principal
# compraron antes con alts. Este op: (1) resuelve usernames pump.fun de los holders, (2) lista primeros compradores,
# (3) busca vínculos (transferencias de SOL / fondeo común) entre principales y compradores tempranos.
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 540 python3 - <<'PY'
import os, requests, json, time, collections
MINT = "5wCqCq6jbppuTocMeq6zd4UywAm64L1QNNxvEDAHpump"
ST = "https://data.solanatracker.io"; SH = {"x-api-key": os.environ.get("SOLANATRACKER_API_KEY", "")}
HK = os.environ.get("HELIUS_API_KEY", "")
NAMES = ["dior","capexbt","bob","marcell","cooker","zenfishechoingg","harrypauldavies","trenchwarior","ohtwoo","ely",
         "roaringkitty","sicktuna36965","bonk_guy","slang","coreyape","tvdj","tag911","nftdefi","80scarpediem","isock"]
OUT = {"mint": MINT, "ts": time.time()}

def get(url, h=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=h or {}, timeout=25)
            if r.status_code == 429: time.sleep(2 + 2*i); continue
            if r.status_code != 200: return {"_status": r.status_code, "_body": r.text[:200]}
            return r.json()
        except Exception as e:
            err = str(e)
    return {"_err": err if 'err' in dir() else "retries"}

def sample(tag, j): print(f"--- {tag}:", json.dumps(j)[:700])

# 1) token + primeros compradores + holders + top traders
tok = get(f"{ST}/tokens/{MINT}", SH); sample("token", {k: tok.get(k) for k in ("token","pools","risk","creation")} if isinstance(tok, dict) else tok)
fb = get(f"{ST}/first-buyers/{MINT}", SH); sample("first-buyers", fb)
hold = get(f"{ST}/tokens/{MINT}/holders", SH); sample("holders", hold)
tt = get(f"{ST}/top-traders/{MINT}", SH); sample("top-traders", tt)

def wallets_of(j):
    if isinstance(j, dict):
        for k in ("accounts", "holders", "data", "traders", "buyers"):
            if isinstance(j.get(k), list): j = j[k]; break
    out = []
    for x in (j if isinstance(j, list) else []):
        w = x.get("wallet") or x.get("owner") or x.get("address")
        if w: out.append((w, x))
    return out

first = wallets_of(fb); holders = wallets_of(hold); traders = wallets_of(tt)
print(f"first={len(first)} holders={len(holders)} traders={len(traders)}")

# 2) usernames pump.fun para holders + traders + primeros
allw = list(dict.fromkeys([w for w, _ in holders + traders + first]))
prof = {}
for w in allw[:260]:
    j = get(f"https://frontend-api-v3.pump.fun/users/{w}")
    if isinstance(j, dict) and j.get("username"):
        prof[w] = {"username": j.get("username"), "followers": j.get("followers"),
                   "x": j.get("x_username") or j.get("twitter") or j.get("twitter_username"),
                   "raw_keys": sorted(j.keys())[:25]}
    time.sleep(0.12)
print("perfiles con username:", len(prof))
if prof: sample("perfil ejemplo", next(iter(prof.values())))
mains = {w: p for w, p in prof.items() if p["username"].lower() in NAMES}
print("PRINCIPALES ENCONTRADAS:", len(mains))
for w, p in mains.items(): print("  ", p["username"], w, "x=", p["x"])
OUT["mains"] = mains; OUT["profiles"] = prof

fbmap = {w: x for w, x in first}
early = [w for w, _ in first]
# 3) compradores tempranos: quiénes son principales (por nombre) y qué hicieron
print("\n=== PRIMEROS COMPRADORES (orden) ===")
for i, (w, x) in enumerate(first[:100]):
    nm = prof.get(w, {}).get("username", "")
    keep = {k: x.get(k) for k in ("first_buy_time","first_buy","total_invested","realized","unrealized","total","held","sold","holding","sold_usd","total_sold") if k in x}
    print(i, w, nm, json.dumps(keep)[:300])

# 4) vínculos: transferencias de SOL (Helius enhanced) de cada principal y de cada temprano
def transfers(w, n=100):
    j = get(f"https://api.helius.xyz/v0/addresses/{w}/transactions?api-key={HK}&limit={n}")
    cps = collections.Counter()
    if isinstance(j, list):
        for t in j:
            for nt in (t.get("nativeTransfers") or []):
                a, b, amt = nt.get("fromUserAccount"), nt.get("toUserAccount"), nt.get("amount", 0)
                if amt and amt >= 50_000_000:  # >= 0,05 SOL
                    o = b if a == w else a if b == w else None
                    if o: cps[o] += 1
    return cps
def funded_by(w):
    j = get(f"https://api.helius.xyz/v1/wallet/{w}/funded-by?api-key={HK}")
    if isinstance(j, dict) and not j.get("_status"): return j.get("funder") or j.get("funderAddress") or json.dumps(j)[:120]
    return None

links = []; funders = {}
early_set = set(early[:100])
for w, p in mains.items():
    cps = transfers(w)
    hit = [o for o in cps if o in early_set]
    for o in hit: links.append({"main": p["username"], "main_w": w, "alt": o, "kind": "sol_transfer", "n": cps[o], "early_rank": early.index(o)})
    funders[w] = funded_by(w)
    time.sleep(0.2)
for w in early[:100]:
    funders[w] = funded_by(w); time.sleep(0.1)
    cps = transfers(w, 60)
    hit = [o for o in cps if o in mains]
    for o in hit: links.append({"main": mains[o]["username"], "main_w": o, "alt": w, "kind": "sol_transfer_rev", "n": cps[o], "early_rank": early.index(w)})
# fondeo común
byf = collections.defaultdict(list)
for w, f in funders.items():
    if f and isinstance(f, str) and len(f) in range(32, 45): byf[f].append(w)
for f, ws in byf.items():
    ms = [w for w in ws if w in mains]; es = [w for w in ws if w in early_set and w not in mains]
    if ms and es:
        for m in ms:
            for e in es: links.append({"main": mains[m]["username"], "main_w": m, "alt": e, "kind": "same_funder", "funder": f, "early_rank": early.index(e)})
clusters = {f: ws for f, ws in byf.items() if len(ws) >= 3}
print("\n=== VÍNCULOS principal↔temprano ===")
for l in links: print(json.dumps(l))
print("\n=== GRUPOS DE TEMPRANOS CON MISMO FONDEO (>=3) ===")
for f, ws in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:15]:
    print(f, len(ws), [ (early.index(w) if w in early_set else 'h', prof.get(w,{}).get('username','')) for w in ws])
print("funders muestra:", list(funders.items())[:3])
OUT.update(links=links, clusters=clusters, funders=funders, early=early[:100])
os.makedirs("state/research", exist_ok=True)
json.dump(OUT, open("state/research/tygr_alts.json", "w"))
print("OK guardado state/research/tygr_alts.json")
PY
