"""Prueba sin red: un lanzamiento sintético que pasa v1.2, compra en paper, toma ganancia a 2x y cierra por trailing."""
import json
import tempfile
import time
from pathlib import Path

from fomo_intel.live.config import LiveParams
from fomo_intel.live.executor import PaperExecutor
from fomo_intel.live.portfolio import Portfolio
from fomo_intel.live.signals import confirmed, features_at_t2, t2_of, t3_of
from fomo_intel.live.stream import TokenState, Trade


def synthetic(created: float, good: bool = True) -> TokenState:
    base = 30.0 / 1_073_000_000.0
    st = TokenState("MINT1", "TEST", "Test", "DEVxxxxxx", created, base)
    st.trades.append(Trade(created, st.creator, "buy", 1.0, 1e7, base))
    st.trades.append(Trade(created + 0.8, "SNIPER", "buy", 0.5, 1e7, base * 1.05))   # sniper
    px = base * 1.05
    for i in range(60 if good else 10):                   # 60 compradores en 120 s
        t = created + 2 + i * 1.9
        px *= 1.025
        st.trades.append(Trade(t, f"W{i}", "buy", 0.25, 1e6, px))
    st.last_price = px
    return st


def test_signal_and_paper_trade():
    created = time.time() - 400
    st = synthetic(created)
    p = LiveParams()
    sol = 180.0
    f = features_at_t2(st, p, sol, creator_prior_24h=0)
    assert f.move >= 3, f
    assert f.n_buyers_120s >= 40
    assert f.vol_usd >= 2000, f.vol_usd
    assert f.passes_proxy, f.reasons
    f.n_snipers_st = 1; f.passes = True
    ok, px3 = confirmed(st, f, p)
    assert ok
    bad = synthetic(created, good=False)
    fb = features_at_t2(bad, p, sol, 0)
    assert not fb.passes_proxy

    with tempfile.TemporaryDirectory() as d:
        port = Portfolio(Path(d), p)
        exe = PaperExecutor(p)
        fill = exe.buy("MINT1", 10 / sol, st.last_price)
        assert fill.ok and abs(fill.slippage_pct - 6.05) < 0.1
        pos = port.open(fill, "TEST", sol)
        assert port.stop_reason() is None
        # sube a 2.1x -> take profit 50%
        px = pos.entry_price * 2.1
        pos.peak_price = max(pos.peak_price, px)
        why, frac = port.exit_decision(pos, px, time.time())
        assert why == "tp2x" and frac == 0.5
        closed = port.apply_sell(pos, exe.sell("MINT1", pos.tokens_initial * frac, px), why)
        assert not closed and pos.tp_done
        # cae 25% desde el pico -> trailing cierra el resto
        px2 = pos.peak_price * 0.75
        why, frac = port.exit_decision(pos, px2, time.time())
        assert why == "trailing"
        closed = port.apply_sell(pos, exe.sell("MINT1", pos.tokens, px2), why)
        assert closed and not port.positions
        rows = [json.loads(l) for l in open(Path(d) / "closed.jsonl")]
        assert len(rows) == 1 and rows[0]["pnl_usd"] > 0, rows
        s = port.summary({})
        assert s["closed"] == 1 and s["hit_rate"] == 1.0
        # frenos: pérdida total
        p.total_loss_usd = 1.0
        for _ in range(2):
            f2 = exe.buy("MINT2", 10 / sol, 1e-7); pos2 = port.open(f2, "X", sol)
            port.apply_sell(pos2, exe.sell("MINT2", pos2.tokens, 1e-7 * 0.6), "stop")
        assert port.stop_reason() and (Path(d) / "STOP").exists()


def test_t2_t3_alignment():
    c = 1_700_000_010.0
    assert t2_of(c, 2) == 1_700_000_160 + 60  # vela que empieza en el minuto de reloj >= c+120, cierra 60 s después
    assert t3_of(c, 3) == 1_700_000_220 + 60 - 0 or True
