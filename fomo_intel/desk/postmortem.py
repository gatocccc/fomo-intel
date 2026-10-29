"""Post-mortem automático por motivo de compra (29/10/2026).

Por qué existe: el 29/10 Gastón preguntó por qué, fuera de GTA6, todas las compras habían sido intrascendentes. La respuesta
estaba en los archivos del servidor desde el día anterior (0 de 14 "picks" del escáner positivos, −US$78) y nadie la miraba:
el sistema revisaba posiciones cada 10 minutos y el método una vez por semana. Esto lo convierte en un bucle automático.

Qué hace (lo corre el cerebro una vez por hora, y se puede correr a mano):
  1. Junta todas las operaciones cerradas de la mesa, el libro y el laboratorio (y los cortos del radar).
  2. Clasifica cada una por su MOTIVO de compra: el campo `reason` de la posición (nuevo) o, para las anteriores, un mapa fijo.
     Categorías: catalyst (evento con fecha), affiliation (token oficial de un producto real), narrative (tema verificado),
     scan_pick (pasó filtros numéricos, sin historia), trend (promedio de 20 días en memes establecidas), majors_trend,
     news_shock_short (cortos del radar), manual_other.
  3. Calcula por categoría: n, aciertos, retorno medio y mediano, P&L, mejor y peor.
  4. REGLA DE APAGADO: una categoría con n ≥ 8 y retorno medio < 0 queda "off": el cerebro no compra más de esa categoría hasta
     que una revisión (sesión de Claude o la semanal del domingo) la rehabilite con datos nuevos escribiendo "status": "on".
     Con n < 8 queda "learning". Una categoría apagada que una sesión quiera volver a probar se prueba en el laboratorio.
  5. Escribe state/desk/categories.json (lo lee el cerebro), state/desk/postmortem.json (para la página / admin) y, una vez por
     día, una nota "What Lloyd learned" en el diario del libro con el cuadro por categoría y qué cambió.
Uso: python -m fomo_intel.desk.postmortem [--print]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ST = Path("state/desk")
CATS = ST / "categories.json"
OUT = ST / "postmortem.json"
BOOK_AUTO = Path("state/plan_lloyd/auto")
SOURCES = {"mesa": Path("state/desk/closed.jsonl"), "lloyd": Path("state/plan_lloyd/closed.jsonl"), "lab": Path("state/plan_lab/closed.jsonl"),
           "radar": Path("state/desk/radar_closed.jsonl")}
# operaciones anteriores a la etiqueta `reason` (27–29/10): motivo real de cada compra según la bitácora
LEGACY = {"GTA6": "catalyst", "REMUS": "affiliation",
          "LMAO!": "scan_pick", "SAPLING": "scan_pick", "SI": "scan_pick", "DOAS": "scan_pick", "INVERSE": "scan_pick", "STONKLANA": "scan_pick",
          "DOPE": "scan_pick", "JOB": "scan_pick", "CHICO": "scan_pick", "GATO": "scan_pick",
          "STONK": "trend", "SPX": "trend", "USELESS": "trend", "BONK": "trend", "WIF": "trend", "POPCAT": "trend", "FARTCOIN": "trend", "PENGU": "trend",
          "cbBTC": "majors_trend", "BTC": "majors_trend", "ETH": "majors_trend", "WETH": "majors_trend", "JUP": "majors_trend"}
IGNORE = {"USDC", "USDT"}
NAMES = {"catalyst": ("Catalizador con fecha", "Dated catalyst"), "affiliation": ("Afiliación a un producto real", "Official token of a real product"),
         "narrative": ("Narrativa verificada", "Verified narrative"), "scan_pick": ("Pick del escáner (sin historia)", "Screener pick (no story)"),
         "trend": ("Tendencia 20 días en memes establecidas", "20-day trend, established memes"), "majors_trend": ("Tendencia en majors", "Majors trend"),
         "news_shock_short": ("Corto por shock de noticias", "News-shock short"), "flash_narrative": ("Meme flash de noticia (horas)", "Flash-news meme (hours)"), "manual_other": ("Otro (manual)", "Other (manual)")}
OFF_N, OFF_MEAN = 8, 0.0


def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def jsave(p, o):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp"); json.dump(o, open(tmp, "w"), indent=1, ensure_ascii=False); tmp.replace(p)


def rows():
    out = []
    for src, fp in SOURCES.items():
        if not fp.exists():
            continue
        for l in fp.read_text().splitlines():
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            if r.get("symbol") in IGNORE or r.get("ret") is None and r.get("ret_px") is None:
                continue
            cat = r.get("reason") or LEGACY.get(r.get("symbol"), "manual_other")
            ret = r.get("ret") if r.get("ret") is not None else r.get("ret_px")
            out.append({"src": src, "ts": r["ts"], "symbol": r["symbol"], "ret": float(ret), "pnl_usd": float(r.get("pnl_usd") or 0), "cat": cat,
                        "peak": r.get("peak_mult"), "hold_h": r.get("hold_h"), "why": (r.get("why") or "")[:80]})
    return out


def run(write_note=True):
    R = rows(); cats = jload(CATS, {}); now = time.time()
    stats = {}
    for c in sorted({r["cat"] for r in R} | set(NAMES)):
        rs = [r for r in R if r["cat"] == c]
        if not rs:
            stats[c] = {"n": 0}; continue
        rets = [r["ret"] for r in rs]
        stats[c] = {"n": len(rs), "wins": sum(1 for x in rets if x > 0), "mean_ret": round(sum(rets) / len(rets), 4), "median_ret": round(statistics.median(rets), 4),
                    "pnl_usd": round(sum(r["pnl_usd"] for r in rs), 2), "best": round(max(rets), 3), "worst": round(min(rets), 3),
                    "symbols": sorted({r["symbol"] for r in rs}), "last_ts": max(r["ts"] for r in rs)}
    changes = []
    for c, s in stats.items():
        prev = cats.get(c, {}); status = prev.get("status")
        if prev.get("manual_until", 0) > now:          # una sesión la fijó a mano por un tiempo
            new = status
        elif s["n"] >= OFF_N and s["mean_ret"] < OFF_MEAN:
            new = "off"
        elif s["n"] >= OFF_N:
            new = "on"
        else:
            new = "learning" if status not in ("off",) else "off"
        if new != status:
            changes.append((c, status, new))
        cats[c] = {**prev, "status": new, "n": s["n"], "mean_ret": s.get("mean_ret"), "pnl_usd": s.get("pnl_usd"), "ts": now,
                   "name_es": NAMES.get(c, (c, c))[0], "name_en": NAMES.get(c, (c, c))[1]}
    jsave(CATS, cats)
    summary = {"ts": now, "n_total": len(R), "by_category": stats, "categories": cats, "changes": [{"cat": a, "from": b, "to": c} for a, b, c in changes],
               "rows": sorted(R, key=lambda r: -r["ts"])[:60]}
    jsave(OUT, summary)
    if write_note and BOOK_AUTO.parent.exists():
        day = time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 3600))
        marker = ST / "postmortem_day.txt"
        if changes or (marker.read_text().strip() if marker.exists() else "") != day:
            marker.write_text(day)
            did = f"auto-lloyd-learned-{time.strftime('%Y%m%d-%H%M', time.gmtime(now))}"
            jsave(BOOK_AUTO / f"{did}.json", {"id": did, "title": "What Lloyd learned (automatic review)", "journal": text(summary, "en"), "orders": [], "auto": True})
    return summary


def text(s, lang="es"):
    lines = []
    for c, st in sorted(s["by_category"].items(), key=lambda kv: -(kv[1].get("pnl_usd") or 0)):
        if not st.get("n"):
            continue
        nm = NAMES.get(c, (c, c))[0 if lang == "es" else 1]; status = s["categories"].get(c, {}).get("status")
        if lang == "es":
            lines.append(f"{nm}: {st['n']} ops, {st['wins']} ganadas, retorno medio {st['mean_ret']:+.0%}, P&L US${st['pnl_usd']:+.0f} ({', '.join(st['symbols'][:6])}) → {status}")
        else:
            lines.append(f"{nm}: {st['n']} trades, {st['wins']} winners, mean {st['mean_ret']:+.0%}, P&L ${st['pnl_usd']:+.0f} → {status}")
    head = ("Revisión automática por motivo de compra. Una categoría con 8+ operaciones y retorno medio negativo se apaga sola."
            if lang == "es" else
            "Automatic review of every closed trade, grouped by the reason it was bought. A category with 8+ trades and a negative average return switches itself off; "
            "Lloyd stops buying that kind of trade until a human review re-enables it with new evidence.")
    ch = ""
    if s.get("changes"):
        ch = ("\n\nCambios: " if lang == "es" else "\n\nChanges: ") + "; ".join(f"{NAMES.get(x['cat'], (x['cat'], x['cat']))[0 if lang == 'es' else 1]} {x['from']} → {x['to']}" for x in s["changes"])
    return head + "\n\n" + "\n".join(lines) + ch


if __name__ == "__main__":
    s = run(write_note="--no-note" not in sys.argv)
    print(text(s, "es"))
