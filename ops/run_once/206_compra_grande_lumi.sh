#!/bin/bash
# 31/10 00:30 — Caso LUMI (HvitmAeh6TkToQonoiNwqWcrZsYdYiaSZHP7yMmspump): tvdj compró 14,7 SOL a las 22:27 ART, el consenso (k=4) no disparó
# y lo vimos 48 s tarde. Este op: (1) backtest del gatillo "compra grande de un nombre" sobre los 30 días de kol_buys_30d.json,
# (2) perfiles con audiencia entre los holders de LUMI (TheMarksMan, CILIT_BANG, ...) -> state/desk/kols_extra.json,
# (3) verifica que fomo-radar y el motor del lab levantaron la versión rápida (hilo de 0,5 s + decisiones cada 2 s).
cd /root/fomo_intel || exit 1
set -a; . ./.env; set +a

echo "=== (1) BACKTEST compra grande de un nombre (30 d) ==="
timeout 420 python3 - <<'PY'
import os, json, time, requests, statistics as S, collections
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
buys=json.load(open("state/research/kol_buys_30d.json")); now=time.time()
NAMES={w["wallet"]:w["name"] for w in json.load(open("desk/kols.json"))["wallets"]}
def chart(m,t0):
    for i in range(3):
        try:
            r=requests.get(f"{ST}/chart/{m}?type=1m&time_from={int(t0)-60}&time_to={int(t0)+6*3600+60}",headers=SH,timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json().get("oclhv",[]) if r.status_code==200 else []
        except Exception: time.sleep(1)
    return []
def run(c,tp,sl,hrs,half):
    e=c[0]["close"]*1.03; t0=c[0]["time"]; got=False
    for x in c[1:]:
        if x["time"]>t0+hrs*3600: break
        if sl and x["low"]/e<=1-sl: return (0.5*(tp-1)+0.5*-sl) if got else -sl
        if x["high"]/e>=tp:
            if not half: return tp-1
            got=True
    last=[x for x in c if x["time"]<=t0+hrs*3600][-1]["close"]/e-1
    return (0.5*(tp-1)+0.5*last) if got else last
RULES=[("50% a 2x, resto 30 min",2,None,0.5,True),("TP2 / SL30 / 6h",2,0.3,6,False),("50% a 2x, resto 2 h",2,None,2,True),("TP1.5 / SL25 / 1h",1.5,0.25,1,False)]
# gatillo: primera compra de una billetera en el token con usd >= USD_MIN y mcap (px*1e9) <= CAP_MAX; un evento por token
first={}
for b in sorted(buys,key=lambda b:b["ts"]):
    first.setdefault((b["m"],b["w"]),b)
for USD_MIN,CAP_MAX in ((450,500_000),(450,1_000_000),(900,500_000),(250,300_000)):
    ev={}
    for (m,w),b in first.items():
        usd=float(b.get("usd") or 0); px=float(b.get("px") or 0)
        if usd>=USD_MIN and 0<px*1e9<=CAP_MAX and b["ts"]<now-7*3600 and m not in ev: ev[m]=b
    T=sorted(ev.values(),key=lambda b:b["ts"]); rows=[]; t=time.time()
    for b in T:
        if time.time()-t>90: break
        c=[x for x in chart(b["m"],b["ts"]) if x.get("time",0)>=b["ts"]-60]; time.sleep(0.08)
        if len(c)>=3 and c[0]["close"]>0 and max(x["high"] for x in c)/c[0]["close"]<50: rows.append((b,c))
    print(f"\n--- compra >= US${USD_MIN} con mcap <= US${CAP_MAX/1000:.0f}K: eventos {len(T)}, con velas {len(rows)} ---")
    by=collections.Counter(NAMES.get(b["w"],b["w"][:6]) for b,_ in rows); print("  por nombre:",dict(by.most_common(8)))
    h=len(rows)//2
    for name,*r in RULES:
        for tag,sub in (("todo",rows),("1.ª mitad",rows[:h]),("2.ª mitad",rows[h:])):
            if len(sub)<5: continue
            v=[run(c,*r) for _,c in sub]
            print(f"  {name:24s} {tag:9s} n={len(v):3d} acierto={sum(x>0 for x in v)/len(v):4.0%} prom={S.mean(v):+6.1%} mediana={S.median(v):+6.1%}")
    if USD_MIN==450 and CAP_MAX==500_000:
        json.dump([{"m":b["m"],"sym":b.get("sym"),"ts":b["ts"],"usd":b.get("usd"),"mcap":float(b.get("px") or 0)*1e9,"who":NAMES.get(b["w"],b["w"][:6]),
                    "r_2x30m":run(c,2,None,0.5,True)} for b,c in rows],open("state/research/big_buy_events.json","w"),indent=1)
print("OK backtest")
PY

echo; echo "=== (2) Holders de LUMI con audiencia -> state/desk/kols_extra.json ==="
timeout 240 python3 - <<'PY'
import os, json, time, requests
ST="https://data.solanatracker.io"; SH={"x-api-key":os.environ.get("SOLANATRACKER_API_KEY","")}
MINT="HvitmAeh6TkToQonoiNwqWcrZsYdYiaSZHP7yMmspump"
def get(u,h=None):
    for i in range(3):
        try:
            r=requests.get(u,headers=h or {},timeout=30)
            if r.status_code==429: time.sleep(2+2*i); continue
            return r.json() if r.status_code==200 else None
        except Exception: time.sleep(1)
    return None
def wallets_of(j):
    out=[]
    if isinstance(j,dict):
        for k in ("accounts","holders","data","traders","buyers"):
            if isinstance(j.get(k),list): j=j[k]; break
    if isinstance(j,list):
        for x in j:
            if isinstance(x,dict):
                w=x.get("wallet") or x.get("owner") or x.get("address") or x.get("account")
                if w: out.append((w,x))
    return out
hold=wallets_of(get(f"{ST}/tokens/{MINT}/holders",SH)); tt=wallets_of(get(f"{ST}/tokens/{MINT}/traders",SH) or get(f"{ST}/top-traders/{MINT}",SH))
fb=wallets_of(get(f"{ST}/tokens/{MINT}/first-buyers",SH))
allw=list(dict.fromkeys([w for w,_ in hold+tt+fb]))
print("holders",len(hold),"traders",len(tt),"primeros",len(fb),"únicos",len(allw))
known={w["wallet"] for w in json.load(open("desk/kols.json"))["wallets"]}
prof={}
for w in allw[:250]:
    j=get(f"https://frontend-api-v3.pump.fun/users/{w}"); time.sleep(0.12)
    if isinstance(j,dict) and j.get("username"):
        prof[w]={"username":j["username"],"followers":j.get("followers") or 0,"x":j.get("x_username") or j.get("twitter") or j.get("twitter_username")}
aud=sorted(((w,p) for w,p in prof.items() if (p["followers"] or 0)>=5000 or p["username"].lower() in ("themarksman","cilit_bang")),key=lambda x:-(x[1]["followers"] or 0))
print("perfiles con username:",len(prof),"| con audiencia (>=5K seg.):",len(aud))
for w,p in aud[:40]: print(f"  {p['username']:22s} seg={p['followers']:>7} x={p['x']} {w} {'(ya en lista)' if w in known else ''}")
extra={"_":"31/10 ops 206: perfiles pump.fun con audiencia entre los holders de LUMI (población 'audiencia FOMO', separada de la lista TYGR). fomo-radar la lee sola.",
       "source":"LUMI "+MINT,"ts":time.time(),
       "wallets":[{"wallet":w,"name":p["username"],"followers":p["followers"],"x":p["x"]} for w,p in aud if w not in known]}
os.makedirs("state/desk",exist_ok=True); json.dump(extra,open("state/desk/kols_extra.json","w"),ensure_ascii=False,indent=1)
print("escritas",len(extra["wallets"]),"billeteras nuevas en state/desk/kols_extra.json")
PY

echo; echo "=== (3) Servicios con la versión rápida ==="
sleep 100
systemctl is-active fomo-radar fomo-lab 2>/dev/null; systemctl list-units --type=service --no-pager | grep -i "fomo" | head
journalctl -u fomo-radar --since "-4 min" --no-pager | grep -i "kols" | tail -8
python3 -c "import json;d=json.load(open('state/desk/kols.json'));print({k:d.get(k) for k in ('connected','wallets','buys_seen','fast_thread','big_sol','big_max_mcap_usd','verdict','verdict_big','errors')});print('hot',d.get('hot')[:3])"
tail -5 state/desk/kols_log.jsonl
