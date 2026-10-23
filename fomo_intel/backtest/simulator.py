"""Simulador de ejecución: toma las señales, entra con latencia y slippage penalizados,
y sale por TP escalonado, trailing stop, stop loss, señal de SALIDA o tiempo máximo."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..config import TradingParams
from ..models import BacktestTrade, Signal
from ..sources.store import Store


@dataclass
class _Open:
    token: str
    trader: str
    entry_ts: int
    entry_price: float
    qty: float
    size_usd: float
    signal_kind: str
    probability: float
    peak: float
    realized_usd: float = 0.0
    tp_done: set = field(default_factory=set)


def _fill_price(p: float, side: str, liq: float, tp: TradingParams) -> float:
    slip = tp.slippage_pct_high_liq if liq >= 200_000 else tp.slippage_pct_low_liq
    adj = (1 + slip + tp.fee_pct) if side == "buy" else (1 - slip - tp.fee_pct)
    return p * adj


def run(store: Store, signals: list[Signal], tp: TradingParams, capital_usd: float = 10_000.0,
        min_probability: float = 0.0) -> tuple[list[BacktestTrade], dict]:
    capital = capital_usd
    open_pos: dict[tuple[str, str], _Open] = {}
    closed: list[BacktestTrade] = []
    per_token_exposure: dict[str, float] = defaultdict(float)
    day_pnl: dict[int, float] = defaultdict(float)
    halted_days: set[int] = set()

    def close(pos: _Open, ts: int, price: float, reason: str, frac: float = 1.0):
        nonlocal capital
        liq = store.token_meta.get(pos.token, {}).get("liquidity_usd", 0)
        px = _fill_price(price, "sell", liq, tp)
        qty = pos.qty * frac
        proceeds = qty * px
        cost = qty * pos.entry_price
        pnl = proceeds - cost
        pos.qty -= qty
        pos.realized_usd += pnl
        capital += proceeds
        day_pnl[ts // 86400] += pnl
        per_token_exposure[pos.token] -= cost
        if pos.qty <= 1e-12 or frac >= 1.0:
            total_cost = pos.size_usd
            closed.append(BacktestTrade(token=pos.token, trader=pos.trader, entry_ts=pos.entry_ts,
                                        entry_price=pos.entry_price, exit_ts=ts, exit_price=px, size_usd=total_cost,
                                        pnl_usd=pos.realized_usd, pnl_pct=pos.realized_usd / total_cost,
                                        exit_reason=reason, signal_kind=pos.signal_kind, probability=pos.probability))
            return True
        return False

    # Las salidas se indexan antes de simular: (trader, token) -> [(ts, motivo, fracción)]
    exit_events: dict[tuple[str, str], list[tuple[int, str, float]]] = defaultdict(list)
    for sg in signals:
        k = (sg.trader, sg.token)
        if sg.kind in ("SALIDA_DISTRIBUCION", "SALIDA_DEFENSIVA"):
            exit_events[k].append((int(sg.ts + tp.latency_s), sg.kind.lower(), 1.0))
        elif sg.kind == "CONFIRMACION":
            # call público con cluster adentro: vender una parte en la ola de copiadores
            exit_events[k].append((int(sg.ts + 45), "confirmacion_parcial", tp.confirm_sell_frac))
    for v in exit_events.values():
        v.sort()

    for sig in sorted(signals, key=lambda s: s.ts):
        key = (sig.trader, sig.token)
        if sig.kind.startswith("ENTRADA"):
            if sig.probability < min_probability or key in open_pos:
                continue
            day = sig.ts // 86400
            if day in halted_days or day_pnl[day] < -tp.daily_loss_kill_pct * capital_usd:
                halted_days.add(day)
                continue
            ts = int(sig.ts + tp.latency_s)
            p = store.price_at(sig.token, ts)
            if not p:
                continue
            liq = store.token_meta.get(sig.token, {}).get("liquidity_usd", 0)
            size = min(tp.size_usd * sig.size_multiplier, tp.max_pct_per_trade * capital,
                       tp.max_pct_per_token * capital - per_token_exposure[sig.token])
            if size <= 0 or size > capital:
                continue
            px = _fill_price(p, "buy", liq, tp)
            pos = _Open(sig.token, sig.trader, ts, px, size / px, size, sig.kind, sig.probability, peak=px)
            capital -= size
            per_token_exposure[sig.token] += size
            open_pos[key] = pos
            # recorrer el precio hasta el cierre
            path = store.price_path(sig.token, ts + 1, ts + tp.max_hold_s)
            pending = [e for e in exit_events.get(key, []) if e[0] > ts]
            done = False
            for pts, price in path:
                while pending and pending[0][0] <= pts:
                    ets, reason, frac = pending.pop(0)
                    if close(pos, pts, price, reason, frac):
                        done = True
                        break
                if done:
                    break
                pos.peak = max(pos.peak, price)
                if price <= pos.entry_price * (1 - tp.stop_loss_pct):
                    done = close(pos, pts, price, "stop_loss"); break
                for mult, frac in tp.tp_levels:
                    if mult not in pos.tp_done and price >= pos.entry_price * mult:
                        pos.tp_done.add(mult)
                        remaining_frac = frac / (1 - sum(f for m, f in tp.tp_levels if m in pos.tp_done and m != mult))
                        if close(pos, pts, price, f"tp_{mult:g}x", min(1.0, remaining_frac)):
                            done = True
                if done:
                    break
                if pos.tp_done and price <= pos.peak * (1 - tp.trailing_stop_pct):
                    done = close(pos, pts, price, "trailing_stop"); break
            if not done:
                last = store.price_at(sig.token, ts + tp.max_hold_s) or pos.entry_price
                close(pos, ts + tp.max_hold_s, last, "max_hold")
            open_pos.pop(key, None)

    return closed, metrics(closed, capital_usd)


def metrics(trades: list[BacktestTrade], capital_usd: float) -> dict:
    if not trades:
        return {"n": 0}
    pnl = [t.pnl_usd for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    eq, peak, dd = capital_usd, capital_usd, 0.0
    for t in sorted(trades, key=lambda t: t.exit_ts):
        eq += t.pnl_usd
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.exit_reason] += 1
    return {
        "n": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "expectancy_usd": round(sum(pnl) / len(trades), 2),
        "avg_win_usd": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_usd": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else float("inf"),
        "total_pnl_usd": round(sum(pnl), 2),
        "return_pct": round(sum(pnl) / capital_usd, 3),
        "max_drawdown_pct": round(dd, 3),
        "exit_reasons": dict(reasons),
    }
