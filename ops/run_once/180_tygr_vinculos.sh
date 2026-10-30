#!/bin/bash
# 30/10 — TYGR: 21 billeteras principales de nombres conocidos (resueltas por pump.fun desde Chrome).
# Para cada una: cuándo/a qué precio entró, y si tiene vínculos de SOL con compradores tempranos o top traders (posibles alts).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 560 python3 - <<'PY'
import os, json, time, requests, collections
M="5wCqCq6jbppuTocMeq6zd4UywAm64L1QNNxvEDAHpump"; LAUNCH=1793382349
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}; HK=os.environ.get("HELIUS_API_KEY","")
MAINS={"87rRdssFiTJKY4MGARa4G5vQ31hmR7MxSmhzeaJ5AAxJ":"Dior","H5kB62K51wDU5XabVkiZJXEr8jtkcU4rxtpC6y4gh6td":"capexbt",
"8deJ9xeUvXSJwicYptA9mHsU2rN2pDx37KWzkDkEXhU6":"cooker","6vbrTLsWy76TxDQAUKLqZrPohQuq6EVaJgfGzR82paFa":"marcell",
"FTK2zCVLRa6X1aZ1P3XZU27iAvM8hjHDXiK3BubTEFmW":"bob","DuARUpsEzdVbVpSnbGipLJvWxaXUCPLDJDjNov6Rc6s6":"HarryPaulDavies",
"sUaqf7TGJpWqhbYnv8qHjRm7rRvgXGEa8Y1xvKK9GNA":"trenchwarior","DfMKNnaBbb8TiBv8N6aMUsuJ7eY8e29QDVtzxoxg7sZQ":"zenfishechoingg",
"7bwGevcZDG2nKueEUkQQCLjmGNQ5W59KC8tFaLYAHayQ":"ohtwoo","HVaeUPbAwFhZnY8T3MrUzTWqpHiAbTU1NACmCQdJrqZp":"RoaringKitty(pump)",
"CE44oKS3wpUerx8afyeii56u5oQjBLZknzm4Q2CYHUz9":"ely","3qFD7tnVLqQXvakXUec2jmvQb5D6Tvtbo62vFyfFvVax":"bonk_guy",
"8uRfJP6V7D9ufu2ck4fyFeivFPzu6VvaBTAHoCXCsGi4":"sicktuna","F8iRrHU37EEdvTucGJ5pHTo8V1nGLL8AAxo9duThJFaM":"tvdj",
"3P3Tr5HErnSSqmNrjGXBaACxQj3NmKfi3Efbu5FuuY7i":"coreyape","7xKykf791PTLcb3kGE16VQyz7RLDKJxmStpZNAcAAHb":"slang",
"tAg2tgyHmkGTsmq8wBSKsGvUUgoH37cxmCfRUZSXdtB":"tAg911","FhwFLN5EtYtuUHmetiVxNCBd1tEitFvWwQq1XyizaYMA":"FaZeBlaze",
"4QVFkerWQtRnnP2HpFLz5c8195AYgCN8vrifKaynuNMA":"NFTDefi","Da14vMQWA59rSnGUoJ4XazgP9RJG8egy1HvWxRR7PMS1":"80sCarpeDiem",
"HxEjV6f8Kf6X5MHbsiUh5YC15NwsbDVLLWipxv3FJ72j":"isock"}
def get(u,h=None):
    for i in range(3):
        try:
            r=requests.get(u,headers=h or {},timeout=25)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {"_s":r.status_code,"_b":r.text[:150]}
        except Exception as e: time.sleep(1)
    return {}
d=json.load(open("state/research/tygr_alts.json")); early=d["early"]
fb=get(f"{ST}/first-buyers/{M}",SH); fbm={x["wallet"]:x for x in fb} if isinstance(fb,list) else {}
tt=get(f"{ST}/top-traders/{M}",SH); ttm={x["wallet"]:x for x in tt} if isinstance(tt,list) else {}
# compradores de los primeros 20 min (trades del token, paginado)
buyers={}; cursor=None
for p in range(25):
    u=f"{ST}/trades/{M}?sortDirection=ASC"+(f"&cursor={cursor}" if cursor else "")
    j=get(u,SH); tr=j.get("trades",[]) if isinstance(j,dict) else []
    if p==0: print("trades sample", json.dumps(tr[:1])[:400])
    for t in tr:
        ts=t.get("time",0)/1000
        if t.get("type")=="buy" and ts-LAUNCH<=1200: buyers.setdefault(t.get("wallet"),(round(ts-LAUNCH),round(t.get("volume",0)),round(t.get("priceUsd",0)*1e9)))
    cursor=j.get("nextCursor") if isinstance(j,dict) else None
    if not cursor or not tr or (tr[-1].get("time",0)/1000-LAUNCH)>1200: break
print("compradores primeros 20 min:", len(buyers))
EARLY=set(buyers)|set(early)|set(ttm)
print("\n=== ENTRADA DE CADA PRINCIPAL ===")
for w,n in MAINS.items():
    j=get(f"{ST}/trades/{M}/by-wallet/{w}",SH); tr=j.get("trades",[]) if isinstance(j,dict) else []
    bs=sorted([t for t in tr if t.get("type")=="buy"],key=lambda t:t.get("time",0))
    ss=[t for t in tr if t.get("type")=="sell"]
    if bs:
        b=bs[0]; mc=b.get("priceUsd",0)*1e9
        print(f"{n:20s} 1ra compra +{(b['time']/1000-LAUNCH)/60:5.1f} min  mcap≈US${mc/1e3:6.0f}K  compras={len(bs)} US${sum(t.get('volume',0) for t in bs):7.0f}  ventas={len(ss)} US${sum(t.get('volume',0) for t in ss):7.0f}")
    else: print(f"{n:20s} sin trades ({json.dumps(j)[:120]})")
    time.sleep(0.15)
print("\n=== VÍNCULOS DE SOL principal ↔ compradores tempranos/top traders ===")
def cps(w,pages=3):
    c=collections.Counter(); before=None
    for p in range(pages):
        u=f"https://api.helius.xyz/v0/addresses/{w}/transactions?api-key={HK}&limit=100"+(f"&before={before}" if before else "")
        j=get(u)
        if not isinstance(j,list) or not j: break
        for t in j:
            for nt in (t.get("nativeTransfers") or []):
                a,b,amt=nt.get("fromUserAccount"),nt.get("toUserAccount"),nt.get("amount",0)
                if amt>=20_000_000:
                    o=b if a==w else a if b==w else None
                    if o: c[(o, "out" if a==w else "in")]+=amt/1e9
            for tt_ in (t.get("tokenTransfers") or []):
                if tt_.get("mint")==M:
                    a,b=tt_.get("fromUserAccount"),tt_.get("toUserAccount")
                    o=b if a==w else a if b==w else None
                    if o: c[(o,"TYGR_"+("out" if a==w else "in"))]+=1
        before=j[-1].get("signature")
    return c
allhits=[]
for w,n in MAINS.items():
    c=cps(w)
    hits=[(o,k,round(v,2)) for (o,k),v in c.items() if o in EARLY or o in MAINS or k.startswith("TYGR")]
    top=[(o[:6],k,round(v,1)) for (o,k),v in c.most_common(5)]
    print(f"{n}: {len(c)} contrapartes; vínculos: {hits[:8]}; top: {top}")
    for h in hits: allhits.append((n,)+h)
    time.sleep(0.2)
print("\n=== FONDEO de principales ===")
fund={}
for w,n in MAINS.items():
    j=get(f"https://api.helius.xyz/v1/wallet/{w}/funded-by?api-key={HK}")
    fund[w]=(j.get("funder"),j.get("funderName"),j.get("funderType")) if isinstance(j,dict) else None
    print(n, fund[w]); time.sleep(0.1)
# temprano fondeado por el mismo fondeador privado que una principal
pf=[f[0] for f in fund.values() if f and f[0] and not f[2]]
efund=d.get("funders",{})
for w,f in efund.items():
    if f in pf: print("MISMO FONDEADOR PRIVADO:", w, "rank", early.index(w) if w in early else "?", "funder", f, [MAINS[m] for m,x in fund.items() if x and x[0]==f])
# qué hicieron los grupos con fondeo privado común
print("\n=== GRUPOS TEMPRANOS (fondeo privado común) ===")
for f in ["F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe","B48kNVXs4YK4amkBCH2XokQiv1SeiVQGHDR17xDeKAAn","u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w","is6MTRHEgyFLNTfYcuV4QBWLjrZBfmhVNYR6ccgr8KV","iGdFcQoyR2MwbXMHQskhmNsqddZ6rinsipHc4TNSdwu","8mowmVCEewZ9W2cEaQyQeQEeSxhGr1hvRviLwozwNtBt"]:
    ws=[w for w,x in efund.items() if x==f]
    inv=sum(fbm.get(w,{}).get("total_invested",0) for w in ws); rl=sum(fbm.get(w,{}).get("realized",0) for w in ws); ur=sum(fbm.get(w,{}).get("unrealized",0) for w in ws)
    held=sum(1 for w in ws if fbm.get(w,{}).get("holding",0)>0)
    j=get(f"https://api.helius.xyz/v1/wallet/{f}/funded-by?api-key={HK}")
    print(f[:6], "billeteras", len(ws), "invertido US$", round(inv), "realizado", round(rl), "no realizado", round(ur), "siguen holdeando", held, "| fondeador del fondeador:", (j.get("funderName") or (j.get("funder") or "")[:6]) if isinstance(j,dict) else "")
json.dump({"allhits":allhits,"fund":fund},open("state/research/tygr_vinculos.json","w"))
print("OK")
PY
