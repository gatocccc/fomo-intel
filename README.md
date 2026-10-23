# fomo_intel — fase 1 (sin capital)

Motor de inteligencia sobre traders de FOMO: mapa de side wallets, reconstrucción de calls
y backtest de reglas de entrada/salida. Solana primero; el diseño es agnóstico de cadena.

## Instalación (Hetzner, Python 3.11+)

```bash
git clone <repo> fomo_intel && cd fomo_intel
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar claves
set -a; . ./.env; set +a
```

## Flujo

```bash
# 0) smoke test sin claves (datos sintéticos con el patrón Anglio)
python -m fomo_intel.cli synth && python -m fomo_intel.cli cluster && python -m fomo_intel.cli events && python -m fomo_intel.cli backtest

# 1) datos reales: 90 días de las 7 wallets semilla + candidatas de primer salto
rm -rf data/*            # importante: borrar el sintético
python -m fomo_intel.cli fetch --days 90

# 2) clusters por trader -> data/clusters.json (con evidencia por wallet)
python -m fomo_intel.cli cluster

# 3) calls y variante (frontrun / holdeo_vidriera / baiting / conviccion) -> data/events.json
python -m fomo_intel.cli events

# 4) señales + simulación con fills penalizados -> data/backtest.json
python -m fomo_intel.cli backtest --capital 10000 --min-prob 0.3
```

## Qué hace cada módulo

| Módulo | Función |
| --- | --- |
| `sources/helius.py` | Historial parseado por wallet (swaps y transferencias) y fuente de fondeo |
| `sources/solanatracker.py` | Leaderboard FOMO, trades, liquidez/edad del token, precio histórico 1m |
| `sources/store.py` | Almacén JSON reproducible (en fase 2: PostgreSQL/Timescale) |
| `graph/candidates.py` | Expande candidatas a 2 saltos: a quién fondeó, co-compradores en ventana, depósito CEX compartido |
| `graph/scoring.py` | Puntaje 0-100 con cinco señales y evidencia (tx) por cada una |
| `events/reconstruct.py` | Cada primera compra pública = call; mide cluster antes/después y clasifica |
| `backtest/signals.py` | Motor de señales (mismo código que en tiempo real en fase 2) |
| `backtest/probability.py` | Probabilidad de éxito por tipo de señal y trader (frecuencias suavizadas) |
| `backtest/simulator.py` | Entradas con latencia+slippage, TP escalonado, trailing, stop, salida por distribución, kill switch diario |

## Parámetros

Todos en `fomo_intel/config.py` (`ClusterParams`, `EventParams`, `TradingParams`). Los pesos del
scoring, las ventanas temporales y las reglas de salida se tunean contra `data/events.json`.

## Criterio para pasar a fase 2 (paper trading en vivo)

Con 90 días reales: expectancy positiva neta de fees, drawdown máximo < 25 %, ≥ 40 trades y
≥ 5 traders con cluster de confianza ≥ 70.

## Operación en vivo (fase 2, 23/10/2026)

`fomo_intel/live/` — bot que escucha pump.fun en tiempo real (PumpPortal), mide v1.2 con las mismas
definiciones del backtest, confirma al minuto 3 y opera con frenos. Modo `paper` (simulado) o `real`.

```bash
python -m fomo_intel.live.bot          # lee .env; estado en state/ (positions, trades.jsonl, closed.jsonl, live_summary.json)
```

- Parámetros editables en caliente: `state/control.json` (tamaño, frenos, trading_enabled, panic).
- `state/STOP`: si existe no se abren posiciones (lo crean los frenos automáticos; borrarlo para rearmar).
- Despliegue: GitHub `gatocccc/fomo-intel` (main) -> el servidor se sincroniza solo cada minuto
  (`scripts/server_sync.sh`), publica su estado en la rama `server-state` y ejecuta una vez cada
  script nuevo en `ops/run_once/`.
- Instalación inicial: `bash scripts/server_bootstrap.sh` desde el Mac (una sola vez).
