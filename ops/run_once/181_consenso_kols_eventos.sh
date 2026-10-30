#!/bin/bash
# 30/10 — Backtest "consenso de KOLs" (hipótesis de Gastón, caso TYGR). Paso 1: bajar 30 días de trades de las 21 principales
# y listar eventos: >=3 principales distintas compran el mismo token en <=30 min. Precio/mcap en el gatillo (3.ª compra).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a
timeout 570 python3 - <<'PY'
import os, json, time, requests, collections
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
MAINS=json.load(open("state/research/tygr_vinculos.json"))["fund"].keys()
NAMES=dict(zip(MAINS, ["Dior","capexbt","cooker","marcell","bob","HarryPaulDavies","trenchwarior","zenfish","ohtwoo","RoaringKitty(pump)","ely","bonk_guy","sicktuna","tvdj","coreyape","slang","tAg911","FaZeBlaze","NFTDefi","80sCarpeDiem","isock"]))
SOLM={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY8NnhrbPKjtaFq1"}
since=time.time()-30*86400; buys=[]
def get(u):
    for i in range(4):
        try:
            r=requests.get(u,headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else {}
        except Exception: time.sleep(1)
    return {}
t0=time.time()
for w in MAINS:
    cur=None; n=0; oldest=None
    for p in range(60):
        if time.time()-t0>480: break
        j=get(f"{ST}/wallet/{w}/trades"+(f"?cursor={cur}" if cur else ""))
        tr=j.get("trades",[]) if isinstance(j,dict) else []
        if p==0 and w==list(MAINS)[0]: print("sample", json.dumps(tr[:1])[:500])
        stop=False
        for t in tr:
            ts=t.get("time",0)/1000
            if ts<since: stop=True; break
            to=(t.get("to") or {}); fr=(t.get("from") or {})
            tm=to.get("address"); fm=fr.get("address")
            if fm in SOLM and tm and tm not in SOLM:
                buys.append({"w":w,"m":tm,"sym":(to.get("token") or {}).get("symbol"),"ts":ts,"usd":(t.get("volume") or {}).get("usd") if isinstance(t.get("volume"),dict) else t.get("volume"),
                             "px":(t.get("price") or {}).get("usd") if isinstance(t.get("price"),dict) else t.get("price")})
                n+=1
            oldest=ts
        cur=j.get("nextCursor") if isinstance(j,dict) else None
        if stop or not cur or not tr: break
    print(f"{NAMES[w]:18s} compras 30d: {n:5d}  más vieja: {time.strftime('%m-%d %H:%M',time.gmtime(oldest)) if oldest else '-'}")
json.dump(buys,open("state/research/kol_buys_30d.json","w"))
# eventos de consenso
bym=collections.defaultdict(list)
for b in buys: bym[b["m"]].append(b)
ev=[]
for m,bs in bym.items():
    bs.sort(key=lambda b:b["ts"]); seen={}
    for b in bs:
        seen.setdefault(b["w"],b)
        firsts=sorted(seen.values(),key=lambda b:b["ts"])
        # ventana de 30 min que termina en esta compra
        win=[x for x in firsts if b["ts"]-x["ts"]<=1800]
        if len(win)>=3:
            ev.append({"m":m,"sym":b["sym"],"trigger_ts":b["ts"],"trigger_px":b["px"],"who":[NAMES[x["w"]] for x in win],"first_ts":firsts[0]["ts"],"n_total":len(set(x["w"] for x in bs))}); break
ev.sort(key=lambda e:e["trigger_ts"])
print(f"\nEVENTOS de consenso (>=3 en 30 min): {len(ev)} sobre {len(bym)} tokens comprados")
for e in ev: print(time.strftime('%m-%d %H:%M',time.gmtime(e["trigger_ts"])), e["sym"], e["m"], "px", e["trigger_px"], "quienes", e["who"], "total KOLs", e["n_total"])
json.dump(ev,open("state/research/kol_consenso_eventos.json","w"))
print("OK")
PY
