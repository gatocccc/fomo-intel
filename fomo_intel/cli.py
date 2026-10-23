"""CLI de fase 1.

  python -m fomo_intel.cli synth                      # datos sintéticos en data/
  python -m fomo_intel.cli fetch --days 90            # descarga real (Helius + Solana Tracker)
  python -m fomo_intel.cli cluster                    # mapa de clusters -> data/clusters.json
  python -m fomo_intel.cli events                     # calls y variantes -> data/events.json
  python -m fomo_intel.cli backtest --capital 10000   # señales + simulación -> data/backtest.json
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict

from .backtest.probability import ProbabilityModel
from .backtest.signals import generate_signals
from .backtest.simulator import run
from .config import SEED_TRADERS, Settings
from .events.reconstruct import build_events, summarize
from .graph.candidates import find_candidates
from .graph.scoring import score_cluster
from .models import Cluster, ClusterMember, Evidence
from .sources.store import Store


def _load_clusters(path: str) -> list[Cluster]:
    raw = json.load(open(path))
    return [Cluster(c["trader"], c["public_wallet"],
                    [ClusterMember(m["wallet"], m["score"], [Evidence(**e) for e in m["evidence"]]) for m in c["members"]])
            for c in raw]


def cmd_synth(s: Settings, a):
    from .synth import generate
    store = Store(s.data_dir)
    truth = generate(store, seed=a.seed, n_calls=a.calls)
    json.dump(truth, open(f"{s.data_dir}/truth.json", "w"), indent=1)
    print(f"sintético: {len(store.trades)} trades, {len(store.transfers)} transferencias, {len(store.prices)} tokens")


def cmd_fetch(s: Settings, a):
    from .sources.helius import HeliusClient
    from .sources.solanatracker import SolanaTrackerClient
    store = Store(s.data_dir)
    since = int(time.time()) - a.days * 86400
    hel = HeliusClient(s.helius_api_key)
    st = SolanaTrackerClient(s.solanatracker_api_key) if s.solanatracker_api_key else None
    traders = {k: v for k, v in SEED_TRADERS.items() if not a.trader or k in a.trader}
    raw_dir = __import__("pathlib").Path(s.data_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def fetch_cached(wallet: str, max_pages: int = 50) -> list[dict]:
        """Transacciones crudas en data/raw/<wallet>.json; solo llama a Helius si no están."""
        p = raw_dir / f"{wallet}.json"
        if p.exists() and not a.refresh:
            return [tx for tx in json.load(open(p)) if tx.get("timestamp", 0) >= since]
        txs = hel.wallet_transactions(wallet, since, max_pages=max_pages)
        json.dump(txs, open(p, "w"))
        return txs

    for handle, w in traders.items():
        txs = fetch_cached(w["solana"])
        trades, transfers = hel.parse(w["solana"], txs)
        print(f"@{handle}: {len(txs)} txs -> {store.add_trades(trades)} trades, {store.add_transfers(transfers)} transferencias")
        # segundo nivel: historial de las wallets a las que mandó plata (candidatas)
        for tr in store.transfers_from(w["solana"])[: a.max_candidates]:
            if tr.dst in store.labels:
                continue
            txs2 = fetch_cached(tr.dst, max_pages=10)
            t2, x2 = hel.parse(tr.dst, txs2)
            store.add_trades(t2); store.add_transfers(x2)
            fs = hel.funding_source(tr.dst)
            if fs and fs.get("funderType") == "exchange":
                pass  # fondeada por exchange: se registra pero no se etiqueta como exchange
        store.save()
    if st:
        tokens = {t.token for t in store.trades}
        for tok in tokens:
            if tok in store.token_meta:
                continue
            try:
                store.token_meta[tok] = st.token_meta(tok)
                first = min(t.ts for t in store.trades_in_token(tok))
                store.prices[tok] = st.price_history(tok, first - 600, first + 3 * 86400)
            except Exception as e:  # noqa: BLE001
                print(f"  token {tok[:8]}: sin meta/precio ({e})")
        store.save()
    print("guardado en", s.data_dir)


def cmd_cluster(s: Settings, a):
    store = Store(s.data_dir)
    publics = {k: v["solana"] for k, v in SEED_TRADERS.items()}
    if (s.data_dir + "/truth.json") and __import__("os").path.exists(f"{s.data_dir}/truth.json"):
        truth = json.load(open(f"{s.data_dir}/truth.json"))
        publics = {k: v["public"] for k, v in truth.items() if isinstance(v, dict)}
    out = []
    for handle, pub in publics.items():
        if not store.trades_of(pub):
            continue
        cands = find_candidates(store, pub, s.cluster, s.events)
        cl = score_cluster(store, handle, pub, cands, s.cluster)
        out.append(cl.to_dict())
        print(f"@{handle}: {len(cands)} candidatas -> {len(cl.confirmed())} confirmadas, {len(cl.probable())} probables")
        for m in cl.members:
            print(f"   {m.wallet[:10]}… score={m.score:3d} ({m.confidence}): " + "; ".join(e.signal for e in m.evidence))
    json.dump(out, open(f"{s.data_dir}/clusters.json", "w"), indent=1)


def cmd_events(s: Settings, a):
    store = Store(s.data_dir)
    clusters = _load_clusters(f"{s.data_dir}/clusters.json")
    all_ev = []
    for cl in clusters:
        evs = build_events(store, cl, s.events)
        all_ev += evs
        print(f"@{cl.trader}: {len(evs)} calls -> {summarize(evs)}")
    json.dump([asdict(e) for e in all_ev], open(f"{s.data_dir}/events.json", "w"), indent=1, default=str)


def cmd_backtest(s: Settings, a):
    store = Store(s.data_dir)
    clusters = _load_clusters(f"{s.data_dir}/clusters.json")
    events = [e for cl in clusters for e in build_events(store, cl, s.events)]
    # entrenar probabilidad con la primera mitad, backtestear la segunda (sin mirar el futuro)
    events.sort(key=lambda e: e.ts)
    cut = events[len(events) // 2].ts if events else 0
    prob = ProbabilityModel().fit([e for e in events if e.ts < cut])
    signals = [sg for sg in generate_signals(store, clusters, s.events, prob) if sg.ts >= cut]
    trades, m = run(store, signals, s.trading, capital_usd=a.capital, min_probability=a.min_prob)
    print("señales:", {k: sum(1 for x in signals if x.kind == k) for k in sorted({x.kind for x in signals})})
    print("tabla de probabilidad:", prob.table())
    print("métricas:", json.dumps(m, indent=1))
    json.dump({"metrics": m, "trades": [asdict(t) for t in trades], "signals": [asdict(x) for x in signals]},
              open(f"{s.data_dir}/backtest.json", "w"), indent=1)


def cmd_launches(s: Settings, a):
    """Descarga lanzamientos (graduados + latest) con presupuesto de requests y arma perfiles de deployer."""
    from .launches import LaunchFetcher, deployer_profiles, launch_features
    f = LaunchFetcher(s.solanatracker_api_key, s.data_dir)
    budget = a.budget
    mints: list[tuple[str, bool | None]] = []
    if a.graduated:
        for t in f.graduated():
            tok = t.get("token", t)
            m = tok.get("mint") or t.get("mint")
            if m:
                mints.append((m, True))
        print(f"graduados listados: {len(mints)}")
    if a.latest:
        n0 = len(mints)
        for t in f.latest():
            tok = t.get("token", t)
            m = tok.get("mint") or t.get("mint")
            if m:
                mints.append((m, None))
        print(f"latest listados: {len(mints) - n0}")
    done = 0
    for m, g in mints:
        if f.requests_made + 3 > budget:
            print(f"presupuesto alcanzado ({f.requests_made} requests)")
            break
        L = f.fetch_launch(m, g)
        if L:
            done += 1
            fe = launch_features(L)
            print(f"{L.symbol:>10} {'GRAD' if L.graduated else '    '}{' RUG' if L.rugged else '    '} {fe['launchpad']:<8} dev={L.deployer[:6]} mcap=${L.market_cap_usd:,.0f} snipers={fe['n_snipers']}(in:{fe['snipers_still_in']}) bundl={fe['n_bundlers']} top10={L.top10_pct:.0f}% 24h={fe['ret_24h_pct']}%")
    print(f"tokens guardados: {done} (requests usados: {f.requests_made})")
    prof = deployer_profiles(f.load_all())
    multi = {k: v for k, v in prof.items() if v["launches"] >= 2}
    json.dump(prof, open(f"{s.data_dir}/deployers.json", "w"), indent=1)
    print(f"deployers: {len(prof)}, con 2+ lanzamientos: {len(multi)}")
    for k, v in sorted(multi.items(), key=lambda kv: -kv[1]["launches"])[:15]:
        print(f"  {k[:8]} launches={v['launches']} grad={v['grad_rate']:.0%} rug={v['rug_rate']:.0%} snipers={v['avg_snipers']} bundlers={v['avg_bundlers']} pads={v['launchpads']}")


def cmd_charts(s: Settings, a):
    """Baja precio por minuto de los lanzamientos buenos y muertos (1 request por token)."""
    from .charts import ChartFetcher, select_tokens
    from .launches import LaunchFetcher
    launches = LaunchFetcher(s.solanatracker_api_key, s.data_dir).load_all()
    good, dead = select_tokens(launches)
    targets = [(L, "BUENO") for L in good] + [(L, "MUERTO") for L in dead]
    if a.all:
        seen = {L.mint for L, _ in targets}
        targets += [(L, "MEDIO" if L.graduated else "NOGRAD") for L in launches if L.mint not in seen and L.created_ts > 0]
    f = ChartFetcher(s.solanatracker_api_key, s.data_dir)
    pending = [t for t in targets if not f.have(t[0].mint)]
    print(f"objetivo: {len(good)} buenos + {len(dead)} muertos + {sum(1 for _, t in targets if t == 'MEDIO')} medio + {sum(1 for _, t in targets if t == 'NOGRAD')} no graduados = {len(targets)}; ya bajados: {len(targets)-len(pending)}; a bajar: {len(pending)}")
    ok = fail = 0
    for L, tag in pending:
        if f.requests_made + 2 > a.budget:
            print(f"presupuesto alcanzado ({f.requests_made} requests)")
            break
        try:
            c = f.fetch(L.mint, L.created_ts, hours=a.hours)
            ok += 1
            span = (c[-1]["t"] - c[0]["t"]) / 60 if c else 0
            print(f"{L.symbol:>10} {tag:<6} velas={len(c):4d} cubre={span:5.0f} min  primera=${c[0]['c']:.8f} max=${max(x['h'] for x in c):.8f}" if c else f"{L.symbol:>10} {tag:<6} SIN VELAS")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"{L.symbol:>10} {tag:<6} ERROR {e}")
    print(f"listo: {ok} bajados, {fail} con error, requests usados: {f.requests_made}")


def cmd_entrysim(s: Settings, a):
    """Simula entradas a N minutos de la creación con velas reales (sin usar el resultado para decidir)."""
    from .backtest.entrysim import SimParams, simulate, summarize
    from .charts import ChartFetcher, select_tokens
    from .launches import LaunchFetcher
    launches = {L.mint: L for L in LaunchFetcher(s.solanatracker_api_key or "x", s.data_dir).load_all()}
    charts = ChartFetcher(s.solanatracker_api_key or "x", s.data_dir).load_all()
    good, dead = select_tokens(list(launches.values()))
    label = {m: ("MEDIO" if L.graduated else "NOGRAD") for m, L in launches.items()}
    label.update({L.mint: "BUENO" for L in good}); label.update({L.mint: "MUERTO" for L in dead})
    mints = [m for m in charts if m in launches]
    for entry in a.entry:
        p = SimParams(entry_min=entry, slippage=a.slippage, fee=a.fee, stop=a.stop, trail=a.trail, max_hold_min=int(a.hours * 60), fill=a.fill)
        res = [simulate(m, launches[m].symbol, launches[m].created_ts, charts[m]["candles"], p) for m in mints]
        print(f"\n=== entrada a {entry} min | compra al {a.fill} de la vela | slippage {a.slippage:.0%} fee {a.fee:.0%} stop {a.stop:.0%} trailing {a.trail:.0%} ===")
        print(json.dumps(summarize(res), indent=1, ensure_ascii=False))
        for tag in ("BUENO", "MEDIO", "MUERTO", "NOGRAD"):
            sub = [r for r in res if label.get(r.mint, "MEDIO") == tag]
            if sub:
                sm = summarize(sub)
                print(f"  {tag:<6} candidatos={len(sub)} entradas={sm.get('entradas',0)} aciertos={sm.get('ganadoras',0)} ret_medio={sm.get('retorno_medio',0)} total={sm.get('resultado_total_1usd_cada_una',0)}")
        if a.verbose:
            for r in sorted(res, key=lambda x: -x.ret):
                if r.entered:
                    print(f"   {r.symbol:>10} {label.get(r.mint,'MEDIO'):<6} ret={r.ret:+.2f} pico={r.peak_mult:5.2f}x hold={r.hold_min:4d}min salidas={[ (e[2], e[3]) for e in r.exits ]}")
                else:
                    print(f"   {r.symbol:>10} {label.get(r.mint,'MEDIO'):<6} NO ENTRA ({r.reason})")


def cmd_validate(s: Settings, a):
    """Prueba la regla v1 SOLO sobre lanzamientos que no estaban cuando se diseñó.
    1) congela la lista de tokens de entrenamiento (primera corrida)
    2) baja lanzamientos nuevos (graduados + latest) y sus velas
    3) aplica la regla v1 sin tocarla y acumula el resultado en data/validation.json"""
    from pathlib import Path
    from .backtest.entrysim import SimParams, simulate
    from .backtest.rules import RULESETS, V1, build_context, confirmed, features, rule_v1
    from .charts import ChartFetcher
    from .launches import LaunchFetcher, QuotaExhausted
    frozen_p = Path(s.data_dir) / "rules_v1_frozen.json"
    lf = LaunchFetcher(s.solanatracker_api_key, s.data_dir)
    if not frozen_p.exists():
        json.dump({"frozen_ts": int(time.time()), "mints": [L.mint for L in lf.load_all()]}, open(frozen_p, "w"))
        print("lista de entrenamiento congelada:", len(json.load(open(frozen_p))["mints"]), "tokens")
    frozen = set(json.load(open(frozen_p))["mints"])
    # 1) lanzamientos nuevos
    mints = []
    quota_out = False
    try:
      for t in lf.graduated():
        tok = t.get("token", t); m = tok.get("mint") or t.get("mint")
        if m: mints.append((m, True))
      for t in lf.latest():
        tok = t.get("token", t); m = tok.get("mint") or t.get("mint")
        if m: mints.append((m, None))
    except QuotaExhausted as e:
        print("AVISO:", e); quota_out = True
    new = [(m, g) for m, g in mints if m not in frozen and not (lf.dir / f"{m}.json").exists()]
    print(f"listados: {len(mints)}, nuevos a bajar: {len(new)}")
    # modo barato, en este orden: (A) cerrar provisorios ya maduros (1 request c/u, lo más valioso)
    #                              (B) con lo que quede, bajar lanzamientos nuevos
    from .backtest.rules import V1 as _V1, base_price, entry_candle
    cf = ChartFetcher(s.solanatracker_api_key, s.data_dir)
    launches = {L.mint: L for L in lf.load_all()}
    ctx = build_context(launches)
    log_p = Path(s.data_dir) / "validation.json"
    log = json.load(open(log_p)) if log_p.exists() else {}
    now = int(time.time())
    MATURE = 6.5 * 3600

    def evaluate_one(m, L, candles, final):
        f = features(L, candles, ctx, V1["entry_min"])
        row = {"symbol": L.symbol, "created_ts": L.created_ts, "final": final, "rules": {},
               "compradores": f["n_buyers_entry"], "mov": round(f["move_vs_base"] or 0, 1), "vol": f["vol_usd_entry"], "snipers": f["n_snipers"]}
        for name, (fn, entry_min, tol) in RULESETS.items():
            ok = bool(fn(f)) and (tol is None or confirmed(candles, L.created_ts, entry_min, tol))
            r = simulate(m, L.symbol, L.created_ts, candles, SimParams(entry_min=entry_min, fill="close", **V1["exit"])) if ok else None
            row["rules"][name] = {"pasa": ok, "entro": bool(r and r.entered), "ret": r.ret if r else None, "salidas": [e[3] for e in r.exits] if r else []}
        row["pasa"] = any(v["pasa"] for v in row["rules"].values())
        return row

    n_new = n_closed = 0
    # (A) cerrar
    for m, row in list(log.items()):
        L = launches.get(m)
        if not L or row.get("final") or (now - L.created_ts) < MATURE:
            continue
        if not row.get("pasa"):
            row["final"] = True; continue
        if lf.requests_made + cf.requests_made + 1 > a.budget:
            print("presupuesto agotado cerrando provisorios"); break
        if quota_out: break
        try: cf.fetch(m, L.created_ts, hours=6.0, force=True)
        except QuotaExhausted as e: print("AVISO:", e); quota_out = True; break
        except Exception as e: print(f"  {L.symbol}: no se pudo cerrar ({e})"); continue  # noqa: BLE001
        log[m] = evaluate_one(m, L, json.load(open(cf.dir / f"{m}.json"))["candles"], final=True); n_closed += 1
    print(f"provisorios cerrados: {n_closed} (requests: {lf.requests_made + cf.requests_made})")
    # (B) nuevos
    seen = set(); new = [(m, g) for m, g in new if not (m in seen or seen.add(m))]
    n_full = 0
    for m, g in new:
        if lf.requests_made + cf.requests_made + 3 > a.budget:
            print(f"presupuesto alcanzado ({lf.requests_made + cf.requests_made})"); break
        if quota_out: break
        try:
            L = lf.fetch_launch(m, g, cheap=True)
            if not L or L.created_ts <= 0:
                continue
            candles = cf.fetch(m, L.created_ts, hours=6.0)
        except QuotaExhausted as e: print("AVISO:", e); quota_out = True; break
        except Exception as e: print(f"  {m[:8]}: sin datos ({e})"); continue  # noqa: BLE001
        ec = entry_candle(candles, L.created_ts, _V1["entry_min"]); bp = base_price(candles)
        if ec and bp > 0 and ec["c"] / bp >= _V1["min_move"]:
            try: lf.complete_buyers(L); n_full += 1
            except QuotaExhausted as e: print("AVISO:", e); quota_out = True; break
        launches[m] = L; ctx = build_context(launches)
        log[m] = evaluate_one(m, L, candles, final=(now - L.created_ts) >= MATURE); n_new += 1
    print(f"tokens nuevos evaluados: {n_new}, con compradores (pasaron el primer corte): {n_full}")
    json.dump(log, open(log_p, "w"), indent=1)
    print(f"\nacumulado nunca visto: {len(log)}; finales: {sum(1 for v in log.values() if v.get('final'))}")
    for name in RULESETS:
        for kind, cond in (("FINALES", True), ("PROVISORIAS", False)):
            ops = [v for v in log.values() if v.get("rules", {}).get(name, {}).get("entro") and bool(v.get("final")) == cond]
            if not ops:
                continue
            w = sum(1 for v in ops if v["rules"][name]["ret"] > 0)
            print(f"[{name}] {kind}: {len(ops)} operaciones  aciertos: {w/len(ops):.0%}  resultado (US$1 c/u): {sum(v['rules'][name]['ret'] for v in ops):+.2f}")
            for v in sorted(ops, key=lambda v: -v["rules"][name]["ret"]):
                rr = v["rules"][name]
                print(f"     {v['symbol']:>11} ret={rr['ret']:+.2f} mov={v['mov']}x compradores={v['compradores']} vol=${v['vol']:,.0f} (${v['vol']/max(1,v['compradores']):.0f}/comprador) snipers={v['snipers']} salidas={rr['salidas']}")
    print(f"requests usados: {lf.requests_made + cf.requests_made}")
    # resumen de una línea (lo que importa) + estado para `report`
    summary = {"ts": now, "nunca_vistos": len(log), "quota_out": quota_out, "rules": {}}
    for name in RULESETS:
        fin = [v["rules"][name]["ret"] for v in log.values() if v["rules"].get(name, {}).get("entro") and v.get("final")]
        prov = [v["rules"][name]["ret"] for v in log.values() if v["rules"].get(name, {}).get("entro") and not v.get("final")]
        summary["rules"][name] = {"finales": len(fin), "aciertos": round(sum(1 for r in fin if r > 0) / len(fin), 3) if fin else None,
                                  "total": round(sum(fin), 2), "provisorias": len(prov)}
    json.dump(summary, open(Path(s.data_dir) / "validation_summary.json", "w"), indent=1)
    open(Path(s.data_dir) / "validation_history.jsonl", "a").write(json.dumps(summary) + "\n")
    v = summary["rules"].get("v1.2", {})
    print(f"\nRESUMEN v1.2: {v.get('finales', 0)} operaciones cerradas, {int((v.get('aciertos') or 0) * 100)}% de acierto, {v.get('total', 0):+.2f} por US$1 c/u; {v.get('provisorias', 0)} abiertas" + ("  [CUOTA AGOTADA]" if quota_out else ""))


def cmd_report(s: Settings, a):
    """Muestra el estado de la validación sin usar la API."""
    from pathlib import Path
    sp = Path(s.data_dir) / "validation_summary.json"
    if not sp.exists():
        print("todavía no hay corridas de validate"); return
    sm = json.load(open(sp))
    print(f"última corrida: {time.strftime('%d/%m %H:%M', time.localtime(sm['ts']))}  tokens nunca vistos: {sm['nunca_vistos']}" + ("  [CUOTA AGOTADA]" if sm.get("quota_out") else ""))
    print(f"{'regla':<6} {'cerradas':>8} {'acierto':>8} {'US$1 c/u':>9} {'abiertas':>8}")
    for name, v in sm["rules"].items():
        ac = f"{v['aciertos']:.0%}" if v["aciertos"] is not None else "-"
        print(f"{name:<6} {v['finales']:>8} {ac:>8} {v['total']:>+9.2f} {v['provisorias']:>8}")
    hp = Path(s.data_dir) / "validation_history.jsonl"
    if hp.exists():
        print("\nhistorial v1.2 (cerradas / acierto):")
        for line in open(hp).read().splitlines()[-12:]:
            h = json.loads(line); v = h["rules"]["v1.2"]
            print(f"  {time.strftime('%d/%m %H:%M', time.localtime(h['ts']))}  {v['finales']:>3}  {(v['aciertos'] or 0):.0%}  {v['total']:+.2f}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("synth"); sp.add_argument("--seed", type=int, default=7); sp.add_argument("--calls", type=int, default=25)
    fp = sub.add_parser("fetch"); fp.add_argument("--days", type=int, default=90); fp.add_argument("--trader", nargs="*"); fp.add_argument("--max-candidates", type=int, default=40); fp.add_argument("--refresh", action="store_true", help="ignorar cache raw")
    sub.add_parser("cluster"); sub.add_parser("events")
    lp = sub.add_parser("launches"); lp.add_argument("--budget", type=int, default=300, help="máx requests a Solana Tracker en esta corrida"); lp.add_argument("--graduated", action="store_true"); lp.add_argument("--latest", action="store_true")
    cp = sub.add_parser("charts"); cp.add_argument("--budget", type=int, default=80); cp.add_argument("--hours", type=float, default=6.0, help="horas de historia desde la creación"); cp.add_argument("--all", action="store_true", help="también los graduados del medio y los no graduados")
    ep = sub.add_parser("entrysim"); ep.add_argument("--entry", type=int, nargs="*", default=[2, 5, 10]); ep.add_argument("--slippage", type=float, default=0.05); ep.add_argument("--fee", type=float, default=0.01); ep.add_argument("--stop", type=float, default=0.35); ep.add_argument("--trail", type=float, default=0.25); ep.add_argument("--hours", type=float, default=6.0); ep.add_argument("--verbose", action="store_true"); ep.add_argument("--fill", default="close", choices=["open", "close", "high"])
    vp = sub.add_parser("validate"); vp.add_argument("--budget", type=int, default=400)
    sub.add_parser("report")
    bp = sub.add_parser("backtest"); bp.add_argument("--capital", type=float, default=10_000); bp.add_argument("--min-prob", type=float, default=0.0)
    a = p.parse_args()
    s = Settings()
    {"synth": cmd_synth, "fetch": cmd_fetch, "cluster": cmd_cluster, "events": cmd_events, "backtest": cmd_backtest, "launches": cmd_launches, "charts": cmd_charts, "entrysim": cmd_entrysim, "validate": cmd_validate, "report": cmd_report}[a.cmd](s, a)


if __name__ == "__main__":
    main()
