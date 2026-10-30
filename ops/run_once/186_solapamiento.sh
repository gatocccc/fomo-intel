#!/bin/bash
# 30/10 — Chequeo pedido por Gastón: ¿las 13 billeteras privadas (grupos tempranos de TYGR) son alts de los 21 KOLs?
# Test: solapamiento de tokens en 30 días y ORDEN (compra privada → compra KOL → venta privada = alt que dumpea sobre la audiencia).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 580 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
d=json.load(open("state/research/tygr_alts.json")); fund=d["funders"]
G={"B48kNV":"B48kNVXs4YK4amkBCH2XokQiv1SeiVQGHDR17xDeKAAn","8mowmV":"8mowmVCEewZ9W2cEaQyQeQEeSxhGr1hvRviLwozwNtBt","iGdFcQ":"iGdFcQoyR2MwbXMHQskhmNsqddZ6rinsipHc4TNSdwu","u6PJ8D":"u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w"}
W={w:g for g,f in G.items() for w,x in fund.items() if x==f}
SOLM={"So11111111111111111111111111111111111111112"}
def get(u):
    for i in range(4):
        try:
            r=requests.get(u,headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {}
        except Exception: time.sleep(1)
    return {}
since=time.time()-30*86400; T=[]
for w,g in W.items():
    cur=None
    for p in range(15):
        j=get(f"{ST}/wallet/{w}/trades"+(f"?cursor={cur}" if cur else "")); tr=j.get("trades",[]) if isinstance(j,dict) else []
        stop=False
        for t in tr:
            ts=t.get("time",0)/1000
            if ts<since: stop=True; break
            fa=(t.get("from") or {}).get("address"); ta=(t.get("to") or {}).get("address")
            side="buy" if fa in SOLM else "sell" if ta in SOLM else None
            if side: T.append({"w":w,"g":g,"m":ta if side=="buy" else fa,"side":side,"ts":ts})
        cur=j.get("nextCursor") if isinstance(j,dict) else None
        if stop or not cur or not tr: break
json.dump(T,open("state/research/privados_trades_30d.json","w"))
kol=json.load(open("state/research/kol_buys_30d.json"))
KB=collections.defaultdict(list)
for b in kol: KB[b["m"]].append(b["ts"])
kfirst={m:min(v) for m,v in KB.items()}
print(f"KOLs: {len(kfirst)} tokens en 30 d. Privadas: {len(set(t['m'] for t in T))} tokens.")
for g in G:
    tg=[t for t in T if t["g"]==g]; toks=set(t["m"] for t in tg)
    ov=toks&set(kfirst)
    before_kol=0; sold_after_kol=0; sold_before_kol=0; gaps=[]
    for m in ov:
        pb=min(t["ts"] for t in tg if t["m"]==m and t["side"]=="buy") if any(t["m"]==m and t["side"]=="buy" for t in tg) else None
        ps=[t["ts"] for t in tg if t["m"]==m and t["side"]=="sell"]
        if pb is None: continue
        if pb<kfirst[m]: before_kol+=1; gaps.append((kfirst[m]-pb)/60)
        if ps:
            if max(ps)>kfirst[m]: sold_after_kol+=1
            else: sold_before_kol+=1
    print(f"\n{g}: {len(toks)} tokens; en común con KOLs {len(ov)} ({len(ov)/len(toks):.0%}); de esos, compró antes que el KOL {before_kol}, "
          f"vendió TODO antes de que llegara el KOL {sold_before_kol}, aún vendía después de la compra del KOL {sold_after_kol}; "
          f"minutos entre su compra y la del 1.er KOL: mediana {S.median(gaps) if gaps else 0:.1f}")
# ¿con qué KOL coinciden más? (si fueran alts de alguien, se vería un nombre dominante)
names=dict(zip(json.load(open("state/research/tygr_vinculos.json"))["fund"].keys(),["Dior","capexbt","cooker","marcell","bob","Harry","trench","zenfish","ohtwoo","RK(pump)","ely","bonk_guy","sicktuna","tvdj","coreyape","slang","tAg911","FaZe","NFTDefi","80s","isock"]))
per_kol=collections.Counter(b["w"] for b in kol); per_kol_tokens=collections.defaultdict(set)
for b in kol: per_kol_tokens[b["w"]].add(b["m"])
ptoks=set(t["m"] for t in T)
print("\nKOL: tokens 30d → % de ellos donde alguna privada entró antes")
for w,ts in sorted(per_kol_tokens.items(),key=lambda kv:-len(kv[1])):
    n=len(ts); c=len(ts&ptoks)
    print(f"  {names.get(w,w[:6]):10s} {n:5d} tokens  {c/n:4.0%} con privadas")
# control: los KOLs compraron 6.781 tokens; las privadas ~1.400 de ~300.000 lanzados en 30 d. Solapamiento esperado al azar ≈ 0,5%.
print("OK")
PY
