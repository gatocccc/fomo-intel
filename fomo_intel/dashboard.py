"""FOMO Intel — dashboard HTML estático.

Uso:  python3 -m fomo_intel.dashboard [ruta_salida.html]
Lee data/validation.json y logs/LAST.txt. No consulta la API.
Guarda una foto por corrida en data/dashboard_history.json (solo si cambió algo).
"""
import json, os, sys, html
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAL = os.path.join(BASE, "data", "validation.json")
LAST = os.path.join(BASE, "logs", "LAST.txt")
HIST = os.path.join(BASE, "data", "dashboard_history.json")
ART = timezone(timedelta(hours=-3))
REGLAS = ["v1", "v1.1", "v1.2"]
PRINCIPAL = "v1.2"
CORTE_LIMPIO = 1792725000      # 23/10/2026 00:10 ART: desde acá v1.2 es prueba limpia
META_CERRADAS = 30


# ---------------- operación en vivo (fase 2) ----------------
STATE = os.path.join(BASE, "state")


def _jsonl(name, n=200):
    f = os.path.join(STATE, name)
    if not os.path.exists(f): return []
    rows = []
    with open(f) as fh:
        for line in fh.read().splitlines()[-n:]:
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows


def seccion_live():
    f = os.path.join(STATE, "live_summary.json")
    if not os.path.exists(f):
        return "<h2>Operación en vivo</h2><p class='muted'>El bot todavía no reportó.</p>"
    try: s = json.load(open(f))
    except Exception: return "<h2>Operación en vivo</h2><p class='muted'>Resumen ilegible (se está escribiendo).</p>"
    ahora = datetime.now(ART).timestamp()
    atraso = ahora - s.get("ts", 0)
    vivo = "ok" if atraso < 120 else "alerta"
    stop = s.get("stop_reason")
    stop_file = os.path.exists(os.path.join(STATE, "STOP"))
    modo = s.get("mode", "paper")
    modo_txt = "DINERO REAL" if modo == "real" else "SIMULADO (paper)"
    modo_cls = "rojo" if modo == "real" else "amarillo"
    hit = s.get("hit_rate")
    pnl = s.get("pnl_usd_total", 0) or 0
    wallet = s.get("wallet") or "—"
    wsol = s.get("wallet_sol")
    solusd = s.get("sol_usd") or 0
    saldo = f"{wsol:.3f} SOL (US${wsol*solusd:,.0f})" if wsol is not None else "—"
    estado_bot = ("<span class='loss'>DETENIDO: " + html.escape(str(stop)) + "</span>") if stop else "<span class='win'>operando</span>"
    pos = "".join(
        f"<tr><td><a href='https://solscan.io/token/{p['mint']}' target='_blank'>{html.escape(p['symbol'])}</a></td>"
        f"<td>{p['age_min']:.0f} min</td><td class='{'win' if p['mult']>=1 else 'loss'}'>{p['mult']:.2f}x</td><td>{p['peak_mult']:.2f}x</td>"
        f"<td>US${p['size_usd']:.0f}</td><td>{'✔' if p.get('tp_done') else ''}</td></tr>" for p in s.get("positions", []))
    pos_tbl = ("<table><tr><th>Token</th><th>Edad</th><th>Ahora</th><th>Pico</th><th>Tamaño</th><th>TP hecho</th></tr>" + pos + "</table>") if pos else "<p class='muted'>Sin posiciones abiertas.</p>"
    cerr = _jsonl("closed.jsonl", 100)
    filas = "".join(
        f"<tr><td><a href='https://solscan.io/token/{c['mint']}' target='_blank'>{html.escape(c['symbol'])}</a></td><td>{hora(c['ts'])}</td>"
        f"<td class='{'win' if c['pnl_usd']>0 else 'loss'}'>{c['pnl_usd']:+.2f}</td><td class='{'win' if c['ret']>0 else 'loss'}'>{c['ret']*100:+.0f}%</td>"
        f"<td>{c['peak_mult']:.2f}x</td><td>{c['hold_min']:.0f} min</td><td>{', '.join(c.get('exits', []))}</td></tr>" for c in reversed(cerr))
    cerr_tbl = ("<table><tr><th>Token</th><th>Cerrada</th><th>US$</th><th>Ret</th><th>Pico</th><th>Duración</th><th>Salidas</th></tr>" + filas + "</table>") if cerr else "<p class='muted'>Todavía no hay operaciones cerradas.</p>"
    trades = [t for t in _jsonl("trades.jsonl", 300) if t.get("ok")]
    compras = [t for t in trades if t.get("side") == "buy"]
    slip = [t["slippage_pct"] for t in compras if t.get("slippage_pct") is not None]
    imp = [t["quote_impact_pct"] for t in compras if t.get("quote_impact_pct")]
    slip_txt = f"{sum(slip)/len(slip):+.1f}% promedio en {len(slip)} compras" if slip else "sin compras aún"
    imp_txt = f"{sum(imp)/len(imp):.1f}% promedio (cotización real)" if imp else "—"
    acum, y = [], 0.0
    for c in cerr: y += c["pnl_usd"]; acum.append(y)
    sig = _jsonl("signals.jsonl", 400)
    sig_pasan = [x for x in sig if x.get("passes_proxy")]
    n_comp = sum(1 for x in sig if x.get("decision") == "COMPRADO")
    ult_sig = "".join(
        f"<tr><td>{hora(x['ts'])}</td><td>{html.escape(x.get('symbol','?'))}</td><td>{x.get('move',0):.1f}x</td><td>{x.get('n_buyers_120s',0)}</td>"
        f"<td>{x.get('vol_usd',0):,.0f}</td><td>{x.get('n_snipers_st') if x.get('n_snipers_st') is not None else x.get('n_snipers_proxy')}</td>"
        f"<td>{html.escape(str(x.get('decision')))}</td></tr>" for x in reversed(sig_pasan[-25:]))
    sig_tbl = ("<table><tr><th>Hora</th><th>Token</th><th>Mov.</th><th>Compr.</th><th>Vol US$</th><th>Snip.</th><th>Decisión</th></tr>" + ult_sig + "</table>") if ult_sig else "<p class='muted'>Ninguna señal pasó el primer corte todavía.</p>"
    if s.get("strategy") in ("follow", "factory"):
        fs = [x for x in sig if x.get("wallet")]
        sig_pasan = fs
        ult = "".join(
            f"<tr><td>{hora(x['ts'])}</td><td><a href='https://solscan.io/token/{x['mint']}' target='_blank'>{x['mint'][:8]}…</a></td>"
            f"<td><a href='https://solscan.io/account/{x['wallet']}' target='_blank'>{x['wallet'][:6]}…</a></td><td>{x.get('sol',0):.2f}</td>"
            f"<td>{x.get('mcap_sol',0):,.0f}</td><td>{x.get('n_wallets',1)}</td><td>{html.escape(str(x.get('decision')))}</td></tr>" for x in reversed(fs[-30:]))
        sig_tbl = ("<table><tr><th>Hora</th><th>Token</th><th>Seguido</th><th>SOL</th><th>Mcap SOL</th><th>Seguidos en el token</th><th>Decisión</th></tr>" + ult + "</table>") if ult else "<p class='muted'>Todavía no compró ningún seguido.</p>"
    botones = f"""
<div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0">
<button onclick="api('stop')" style="background:#7f1d1d">⛔ Frenar compras</button>
<button onclick="api('resume')" style="background:#14532d" {'disabled' if not stop_file else ''}>▶ Rearmar</button>
<button onclick="if(confirm('Vende TODAS las posiciones ahora. ¿Seguro?'))api('panic')" style="background:#581c87">🚨 Vender todo</button>
<button onclick="api('unpanic')" style="background:#374151">quitar pánico</button>
<span id="apimsg" class="muted" style="align-self:center"></span></div>
<script>
function api(a){{fetch('/api/'+a,{{method:'POST'}}).then(r=>r.json()).then(j=>{{document.getElementById('apimsg').textContent=j.msg||JSON.stringify(j);setTimeout(()=>location.reload(),1500)}}).catch(e=>document.getElementById('apimsg').textContent='error: '+e)}}
</script>"""
    return f"""
<h2>Operación en vivo — fase 2</h2>
<div class="sem {modo_cls}">{modo_txt} · estrategia <b>{'SEGUIDOR de ' + str(s.get('followed_wallets',0)) + ' billeteras' if s.get('strategy')=='follow' else ('SNIPER de ' + str(s.get('factories',0)) + ' fábricas' if s.get('strategy')=='factory' else 'reglas v1.2')}</b> · bot {estado_bot} · último latido <span class="{vivo}">{hora(s.get('ts',0))}</span>
<div style="font-size:12px;font-weight:400;margin-top:6px">Billetera <a href="https://solscan.io/account/{html.escape(wallet)}" target="_blank">{html.escape(wallet)}</a> · saldo {saldo} · SOL US${solusd:,.0f} ·
stream {'conectado' if s.get('stream_connected') else '<span class=loss>CAÍDO</span>'} · tokens vistos {s.get('tokens_seen',0)} · requests Solana Tracker {s.get('st_requests',0)}</div></div>
{botones}
<div class="grid">
<div class="card"><div class="k">Operaciones cerradas</div><div class="v">{s.get('closed',0)} <span style="font-size:14px">de {s.get('params',{}).get('max_trades','?')}</span></div></div>
<div class="card"><div class="k">Acierto</div><div class="v">{f"{hit*100:.0f}%" if hit is not None else "—"}</div></div>
<div class="card"><div class="k">Resultado US$</div><div class="v {'win' if pnl>0 else 'loss' if pnl<0 else ''}">{pnl:+.2f}</div></div>
<div class="card"><div class="k">Hoy US$</div><div class="v">{(s.get('pnl_usd_today') or 0):+.2f} <span style="font-size:12px">lím. −{s.get('params',{}).get('daily_loss_usd',0):.0f}</span></div></div>
<div class="card"><div class="k">Slippage real (compras)</div><div class="v" style="font-size:16px">{slip_txt}<br><span class="muted" style="font-size:12px">impacto cotizado: {imp_txt}</span></div></div>
<div class="card"><div class="k">Señales que pasaron el corte / compradas</div><div class="v">{len(sig_pasan)} <span style="font-size:14px">/ {n_comp}</span></div></div>
</div>
<h3 style="color:#9ca3af;font-size:14px">Posiciones abiertas ({s.get('open',0)} de {s.get('params',{}).get('max_open','?')})</h3>{pos_tbl}
<h3 style="color:#9ca3af;font-size:14px">Operaciones cerradas</h3>{cerr_tbl}
<h3 style="color:#9ca3af;font-size:14px">{'Compras de las billeteras seguidas' if s.get('strategy')=='follow' else ('Lanzamientos de las fábricas seguidas' if s.get('strategy')=='factory' else 'Últimas señales que pasaron el primer corte')}</h3>{sig_tbl}
<p class="muted">Frenos: US${s.get('params',{}).get('size_usd',0):.0f} por operación · máx {s.get('params',{}).get('max_open','?')} abiertas · pérdida diaria máx US${s.get('params',{}).get('daily_loss_usd',0):.0f} · corte a {s.get('params',{}).get('max_trades','?')} operaciones o −US${s.get('params',{}).get('total_loss_usd',0):.0f} · no compra si el impacto cotizado supera {s.get('params',{}).get('max_slippage_pct',0):.0f}%.</p>
<hr style="border:0;border-top:1px solid #262a33;margin:28px 0">
<h2>Validación histórica (backtest sobre lanzamientos nuevos)</h2>"""


def hora(ts):
    return datetime.fromtimestamp(ts, ART).strftime("%d/%m %H:%M")


def cargar():
    if not os.path.exists(VAL):
        return {}
    with open(VAL) as f:
        return json.load(f)


def ops_de(data, regla):
    ops = []
    for addr, t in data.items():
        r = t.get("rules", {}).get(regla, {})
        if not r.get("entro"):
            continue
        ops.append({
            "addr": addr, "symbol": t.get("symbol", "?"), "ts": t.get("created_ts", 0),
            "final": bool(t.get("final")), "ret": r.get("ret"), "salidas": r.get("salidas") or [],
            "compradores": t.get("compradores"), "vol": t.get("vol"), "snipers": t.get("snipers"),
        })
    ops.sort(key=lambda o: o["ts"])
    return ops


def resumen(ops):
    cerr = [o for o in ops if o["final"] and o["ret"] is not None]
    abi = [o for o in ops if not o["final"]]
    gan = sum(1 for o in cerr if o["ret"] > 0)
    tot = sum(o["ret"] for o in cerr)
    prov = sum(o["ret"] for o in abi if o["ret"] is not None)
    return {"cerradas": cerr, "abiertas": abi, "n": len(cerr),
            "acierto": (gan / len(cerr)) if cerr else 0.0, "total": tot, "provisorio": prov}


def semaforo(res):
    n, ac, tot = res["n"], res["acierto"], res["total"]
    if n >= META_CERRADAS and ac >= 0.60 and tot > 0:
        return "verde", "Criterio cumplido → pasar a paper trading en vivo"
    if n >= META_CERRADAS and ac < 0.55:
        return "rojo", "Criterio fallido → volver a las reglas (Helius, Telegram)"
    if n >= META_CERRADAS:
        return "amarillo", "Zona gris (55–60%) → seguir acumulando"
    return "amarillo", f"Acumulando muestra: faltan {META_CERRADAS - n} cerradas"


def curva_svg(cerr):
    """Resultado acumulado por US$1, operación a operación."""
    if not cerr:
        return "<p class='muted'>Sin operaciones cerradas todavía.</p>"
    acum, y = [], 0.0
    for o in cerr:
        y += o["ret"]; acum.append(y)
    W, H, pad = 720, 220, 30
    lo, hi = min(0.0, min(acum)), max(0.0, max(acum))
    if hi == lo: hi = lo + 1
    xs = lambda i: pad + i * (W - 2 * pad) / max(1, len(acum) - 1)
    ys = lambda v: H - pad - (v - lo) * (H - 2 * pad) / (hi - lo)
    pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(acum))
    circ = "".join(
        f"<circle cx='{xs(i):.1f}' cy='{ys(v):.1f}' r='3' fill='{'#4ade80' if o['ret']>0 else '#f87171'}'>"
        f"<title>{html.escape(o['symbol'])} {o['ret']:+.2f}</title></circle>"
        for i, (v, o) in enumerate(zip(acum, cerr)))
    return (f"<svg viewBox='0 0 {W} {H}' class='curva'>"
            f"<line x1='{pad}' y1='{ys(0):.1f}' x2='{W-pad}' y2='{ys(0):.1f}' stroke='#555' stroke-dasharray='4'/>"
            f"<polyline points='{pts}' fill='none' stroke='#60a5fa' stroke-width='2'/>{circ}"
            f"<text x='{pad}' y='18' fill='#aaa' font-size='12'>acumulado: {acum[-1]:+.2f} (US$1 por operación)</text>"
            f"<text x='{W-pad}' y='{ys(hi):.1f}' fill='#777' font-size='11' text-anchor='end'>{hi:+.1f}</text>"
            f"<text x='{W-pad}' y='{ys(lo)+4:.1f}' fill='#777' font-size='11' text-anchor='end'>{lo:+.1f}</text></svg>")


def guardar_historia(data_resumen, ahora):
    hist = []
    if os.path.exists(HIST):
        try:
            with open(HIST) as f: hist = json.load(f)
        except Exception: hist = []
    foto = {r: {"n": data_resumen[r]["n"], "acierto": round(data_resumen[r]["acierto"], 3),
                "total": round(data_resumen[r]["total"], 2), "abiertas": len(data_resumen[r]["abiertas"])}
            for r in REGLAS}
    if not hist or hist[-1]["fotos"] != foto:
        hist.append({"ts": ahora.timestamp(), "fotos": foto})
        with open(HIST, "w") as f: json.dump(hist, f)
    return hist


def salida_txt(o):
    s = o["salidas"]
    if not s: return "en curso"
    txt = []
    if "tp2x" in s: txt.append("50% al 2x")
    if "trailing" in s: txt.append("trailing")
    if "stop" in s: txt.append("stop")
    return " + ".join(txt) or ", ".join(s)


def fila(o, abierta=False):
    ret = "—" if o["ret"] is None else f"{o['ret']:+.2f}"
    cls = "" if o["ret"] is None else ("win" if o["ret"] > 0 else "loss")
    limpia = "✔" if o["ts"] >= CORTE_LIMPIO else ""
    return (f"<tr><td><a href='https://solscan.io/token/{o['addr']}' target='_blank'>{html.escape(o['symbol'])}</a></td>"
            f"<td>{hora(o['ts'])}</td><td class='{cls}'>{ret}</td><td>{salida_txt(o)}</td>"
            f"<td>{o['compradores']}</td><td>{o['vol']:,.0f}</td><td>{o['snipers']}</td><td>{limpia}</td></tr>")


def tabla(ops, abierta=False):
    if not ops: return "<p class='muted'>Nada por acá.</p>"
    head = "<tr><th>Token</th><th>Creado</th><th>Ret US$1</th><th>Salida</th><th>Compr.</th><th>Vol US$</th><th>Snip.</th><th>Limpia</th></tr>"
    return "<table>" + head + "".join(fila(o, abierta) for o in reversed(ops)) + "</table>"


def render(data):
    ahora = datetime.now(ART)
    res = {r: resumen(ops_de(data, r)) for r in REGLAS}
    hist = guardar_historia(res, ahora)
    p = res[PRINCIPAL]
    color, msg = semaforo(p)
    limpias = [o for o in p["cerradas"] if o["ts"] >= CORTE_LIMPIO]
    g_l = sum(1 for o in limpias if o["ret"] > 0)
    ult = open(LAST).read().strip() if os.path.exists(LAST) else "sin LAST.txt"
    ult_ts = hora(os.path.getmtime(LAST)) if os.path.exists(LAST) else "—"
    atraso_h = (ahora.timestamp() - os.path.getmtime(LAST)) / 3600 if os.path.exists(LAST) else 99
    salud = "ok" if atraso_h < 3.5 else "alerta"
    pct = min(100, int(100 * p["n"] / META_CERRADAS))

    filas_reglas = "".join(
        f"<tr class='{'main' if r == PRINCIPAL else ''}'><td>{r}</td><td>{res[r]['n']}</td>"
        f"<td>{res[r]['acierto']*100:.0f}%</td><td class='{'win' if res[r]['total']>0 else 'loss'}'>{res[r]['total']:+.2f}</td>"
        f"<td>{len(res[r]['abiertas'])}</td><td>{res[r]['provisorio']:+.2f}</td></tr>" for r in REGLAS)

    filas_hist = "".join(
        f"<tr><td>{hora(h['ts'])}</td><td>{h['fotos'][PRINCIPAL]['n']}</td><td>{h['fotos'][PRINCIPAL]['acierto']*100:.0f}%</td>"
        f"<td>{h['fotos'][PRINCIPAL]['total']:+.2f}</td><td>{h['fotos'][PRINCIPAL]['abiertas']}</td></tr>"
        for h in reversed(hist[-25:]))

    n_tokens = len(data); n_pasa = sum(1 for t in data.values() if t.get("pasa"))

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>FOMO Intel</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e5e7eb;margin:0;padding:20px;max-width:1100px;margin:auto}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em}}
.muted{{color:#6b7280}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:16px 0}}
.card{{background:#171a21;border:1px solid #262a33;border-radius:10px;padding:14px}} .card .k{{font-size:12px;color:#9ca3af}} .card .v{{font-size:26px;font-weight:600;margin-top:4px}}
.sem{{border-radius:10px;padding:14px 16px;margin:16px 0;font-weight:600}} .verde{{background:#14532d}} .rojo{{background:#7f1d1d}} .amarillo{{background:#78350f}}
.bar{{background:#262a33;border-radius:6px;height:10px;margin-top:8px}} .bar i{{display:block;height:10px;border-radius:6px;background:#60a5fa;width:{pct}%}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #262a33}} th{{color:#9ca3af;font-weight:500;font-size:12px}}
tr.main td{{background:#1c2130;font-weight:600}} .win{{color:#4ade80}} .loss{{color:#f87171}} a{{color:#93c5fd;text-decoration:none}}
.curva{{width:100%;height:auto;background:#171a21;border-radius:10px;border:1px solid #262a33}}
.ok{{color:#4ade80}} .alerta{{color:#fbbf24}}
button{{color:#fff;border:0;border-radius:8px;padding:10px 14px;font-weight:600;cursor:pointer}} button:disabled{{opacity:.4;cursor:default}}
</style></head><body>
<h1>FOMO Intel</h1>
<p class="muted">Generado {ahora.strftime('%d/%m/%Y %H:%M')} (ART) · última corrida de validación <b class="{salud}">{ult_ts}</b> · {html.escape(ult)}</p>
{seccion_live()}

<div class="sem {color}">{msg}
<div class="bar"><i></i></div>
<div style="font-size:12px;font-weight:400;margin-top:6px">{p['n']} de {META_CERRADAS} cerradas · acierto {p['acierto']*100:.0f}% · acumulado {p['total']:+.2f} ·
prueba limpia (tokens posteriores al 23/10 00:10): {len(limpias)} cerradas, {g_l} ganadas{f" ({100*g_l/len(limpias):.0f}%)" if limpias else ""}</div></div>

<div class="grid">
<div class="card"><div class="k">v1.2 cerradas</div><div class="v">{p['n']}</div></div>
<div class="card"><div class="k">v1.2 acierto</div><div class="v">{p['acierto']*100:.0f}%</div></div>
<div class="card"><div class="k">v1.2 acumulado (US$1 c/u)</div><div class="v {'win' if p['total']>0 else 'loss'}">{p['total']:+.2f}</div></div>
<div class="card"><div class="k">v1.2 abiertas / provisorio</div><div class="v">{len(p['abiertas'])} <span style="font-size:14px">({p['provisorio']:+.2f})</span></div></div>
<div class="card"><div class="k">Tokens vistos / pasan corte</div><div class="v">{n_tokens} <span style="font-size:14px">/ {n_pasa}</span></div></div>
</div>

<h2>Curva v1.2 (cerradas, en orden de creación)</h2>{curva_svg(p['cerradas'])}

<h2>Reglas (v1 y v1.1 son control)</h2>
<table><tr><th>Regla</th><th>Cerradas</th><th>Acierto</th><th>Acumulado</th><th>Abiertas</th><th>Provisorio abiertas</th></tr>{filas_reglas}</table>

<h2>v1.2 — abiertas ({len(p['abiertas'])})</h2>{tabla(p['abiertas'], True)}
<h2>v1.2 — cerradas ({p['n']})</h2>{tabla(p['cerradas'])}

<h2>Historial de corridas (v1.2)</h2>
<table><tr><th>Corrida</th><th>Cerradas</th><th>Acierto</th><th>Acumulado</th><th>Abiertas</th></tr>{filas_hist}</table>
<p class="muted" style="margin-top:24px">Salida: 50% al 2x, resto trailing 20%, stop −30%. "Limpia" ✔ = token creado después de elegir v1.2; solo esos cuentan como prueba honesta.</p>
</body></html>"""


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/var/www/fomo/index.html"
    htm = render(cargar())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w") as f: f.write(htm)
    os.replace(tmp, out)
    print(f"dashboard → {out}")


if __name__ == "__main__":
    main()
