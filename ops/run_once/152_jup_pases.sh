#!/bin/bash
# Prueba real, chica, del pase SOL<->USDC por Jupiter (sin el 0,5% de Solana Tracker): 0,03 SOL ida y vuelta con la billetera del libro.
# Imprime por dónde fue (via), cuánto entró y salió, y el costo del viaje completo. Si Jupiter falla, el executor cae a Solana Tracker solo.
cd /root/fomo_intel
sleep 20   # que terminen de reiniciar los servicios con el código nuevo
echo "--- servicios"; systemctl is-active fomo-mirror fomo-desk@lloyd fomo-app | tr '\n' ' '; echo
echo "--- clave jupiter: $( [ -n "$(grep -s '^JUPITER_API_KEY=' .env | cut -d= -f2)" ] && echo presente || echo 'ausente (va por lite-api)')"
python3 - <<'PY'
import sys, json, time
sys.path.insert(0, ".")
from pathlib import Path
from fomo_intel.live.bot import load_dotenv; load_dotenv()
from fomo_intel.live.config import Env, LiveParams
from fomo_intel.live.executor import RealExecutor, jup_swap_tx, STABLE_MINTS
from fomo_intel.live.wallet import Rpc, load_or_create
from fomo_intel.live.signals import STClient
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"; SOL = "So11111111111111111111111111111111111111112"
env = Env(); rpc = Rpc(env.rpc_url); st = STClient(env.solanatracker_api_key)
kp = load_or_create(Path("secrets/plan_lloyd.json")); pub = str(kp.pubkey())
sol_usd = st.sol_usd() or 100.0
print("billetera", pub, "SOL", round(rpc.sol_balance(pub), 4), "SOL/USD", sol_usd)
# 1) solo cotización
try:
    tx, q = jup_swap_tx(SOL, USDC, int(0.03e9), 1.0, pub, 0.0003)
    print("cotización ok: in", int(q["inAmount"])/1e9, "SOL -> out", int(q["outAmount"])/1e6, "USDC; impacto", q.get("priceImpactPct"), "; ruta", [r["swapInfo"]["label"] for r in q["routePlan"]], "; tx", len(tx), "bytes")
except Exception as e:
    print("COTIZACIÓN FALLÓ:", e); sys.exit(0)
# 2) ida y vuelta real
p = LiveParams(); p.priority_fee_sol = 0.0003; p.min_sol_reserve = 0.02
ex = RealExecutor(p, kp, rpc, env.solanatracker_api_key)
f = ex.buy(USDC, 0.03, 1.0 / sol_usd)
print("IDA  ok=%s via=%s sol=%.6f usdc=%.4f err=%s" % (f.ok, f.raw.get("via"), f.sol, f.tokens, f.error[:120]))
if not f.ok: sys.exit(0)
time.sleep(5)
g = ex.sell(USDC, f.tokens, 1.0 / sol_usd)
print("VUELTA ok=%s via=%s usdc=%.4f sol=%.6f err=%s" % (g.ok, g.raw.get("via"), g.tokens, g.sol, g.error[:120]))
if g.ok:
    cost = f.sol - g.sol
    print("costo del viaje completo: %.6f SOL = US$%.3f = %.2f%% (incluye gas y prioridad; con Solana Tracker eran ~1%% solo de comisión)" % (cost, cost*sol_usd, cost/f.sol*100))
PY
echo "--- últimos logs del mirror"; journalctl -u fomo-mirror --no-pager --since "-5 min" | grep -v httpx | tail -8
