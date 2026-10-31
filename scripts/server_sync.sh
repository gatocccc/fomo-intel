#!/bin/bash
# Corre cada minuto en el servidor (cron). Hace tres cosas:
#  1) si hay código nuevo en GitHub (rama main) lo baja y reinicia el bot si hace falta
#  2) ejecuta una sola vez cada script nuevo en ops/run_once/ (canal de mantenimiento) y guarda la salida en state/ops/
#  3) cada 5 minutos publica el estado (state/, logs) en la rama server-state para seguimiento remoto
set -u
REPO=/root/fomo_intel
STATE_WT=/root/fomo_state
LOCK=/tmp/fomo_sync.lock
exec 9>"$LOCK"; flock -n 9 || exit 0
cd "$REPO" || exit 1
export GIT_SSH_COMMAND="ssh -i /root/.ssh/fomo_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=2"
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
mkdir -p state/ops logs

# ---- 1) código ----
timeout 60 git fetch -q origin main 2>>logs/sync.err || true
LOCAL=$(git rev-parse HEAD 2>/dev/null); REMOTE=$(git rev-parse origin/main 2>/dev/null)
if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
  CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE" 2>/dev/null)
  git reset -q --hard origin/main
  echo "$(date -u +%FT%TZ) actualizado $LOCAL -> $REMOTE" >> logs/sync.log
  if echo "$CHANGED" | grep -q '^requirements'; then python3 -m pip install -q --break-system-packages -r requirements.txt >> logs/sync.log 2>&1 || python3 -m pip install -q -r requirements.txt >> logs/sync.log 2>&1; fi
  if echo "$CHANGED" | grep -Eq '^(fomo_intel/live/|fomo_intel/backtest/rules.py|requirements)'; then
    systemctl restart fomo-live && echo "$(date -u +%FT%TZ) fomo-live reiniciado" >> logs/sync.log
  fi
  if echo "$CHANGED" | grep -q '^fomo_intel/app/'; then systemctl restart fomo-app 2>/dev/null && echo "$(date -u +%FT%TZ) fomo-app reiniciado" >> logs/sync.log; fi
  if echo "$CHANGED" | grep -q '^fomo_intel/live/control_server.py'; then systemctl restart fomo-control 2>/dev/null || true; fi
  if echo "$CHANGED" | grep -Eq '^fomo_intel/(desk/mirror.py|live/executor.py|live/wallet.py|live/signals.py)'; then systemctl is-enabled -q fomo-mirror 2>/dev/null && systemctl restart fomo-mirror && echo "$(date -u +%FT%TZ) fomo-mirror reiniciado" >> logs/sync.log; fi
  if echo "$CHANGED" | grep -Eq '^fomo_intel/(desk/|live/executor.py|live/wallet.py|live/signals.py)'; then systemctl restart fomo-desk 2>/dev/null && echo "$(date -u +%FT%TZ) fomo-desk reiniciado" >> logs/sync.log; for p in lloyd lab agresivo equilibrado tradicional; do systemctl is-enabled -q fomo-desk@$p 2>/dev/null && systemctl restart fomo-desk@$p; done; systemctl is-enabled -q fomo-floor 2>/dev/null && systemctl restart fomo-floor; systemctl is-enabled -q fomo-brain 2>/dev/null && systemctl restart fomo-brain; systemctl is-enabled -q fomo-radar 2>/dev/null && systemctl restart fomo-radar; fi
fi

# ---- 2) mantenimiento: scripts de una sola vez ----
touch state/ops/ran.txt
for f in ops/run_once/*.sh; do
  [ -f "$f" ] || continue
  id=$(basename "$f" .sh)
  grep -qx "$id" state/ops/ran.txt && continue
  echo "$id" >> state/ops/ran.txt
  { echo "== $id $(date -u +%FT%TZ) =="; timeout 600 bash "$f" 9>&-; echo "== exit $? =="; } > "state/ops/$id.out" 2>&1
done

# ---- resultados a 6 h de los tokens que pasaron el primer corte (cada 10 min) ----
MIN=$(date +%M); if [ $((10#$MIN % 10)) -eq 0 ]; then set -a; . ./.env; set +a; timeout 300 python3 -m fomo_intel.live.outcomes 60 >> logs/outcomes.log 2>&1 || true; fi

# ---- dashboard (cada minuto, barato: solo lee archivos) ----
[ -d /var/www/fomo ] && python3 -m fomo_intel.dashboard /var/www/fomo/historico.html >> logs/dashboard.log 2>&1 || true
# portada = mesa autónoma (desde 27/10); el bot anterior queda en /bot.html
[ -d /var/www/fomo ] && { cmp -s dashboard/desk.html /var/www/fomo/index.html || cp dashboard/desk.html /var/www/fomo/index.html; cmp -s dashboard/live.html /var/www/fomo/bot.html || cp dashboard/live.html /var/www/fomo/bot.html; } 2>/dev/null || true

# ---- piloto automático: landing y panel (cada minuto) + certificado cuando el DNS esté listo ----
[ -d /var/www/autopilot ] && { rsync -a --exclude claves.html dashboard/autopilot/ /var/www/autopilot/; cmp -s dashboard/autopilot/claves.html /var/www/fomo/claves.html || cp dashboard/autopilot/claves.html /var/www/fomo/claves.html; } 2>/dev/null || true
MIN=$(date +%M); [ $((10#$MIN % 5)) -eq 2 ] && bash scripts/app_cert.sh 2>/dev/null || true

# ---- 3) publicar estado cada 5 min ----
MIN=$(date +%M); [ "${FORCE_STATE:-0}" = "1" ] || [ $((10#$MIN % 5)) -eq 0 ] || exit 0
if [ ! -d "$STATE_WT/.git" ]; then
  rm -rf "$STATE_WT"; mkdir -p "$STATE_WT"; cd "$STATE_WT"
  git init -q; git checkout -q -b server-state; git remote add origin "$(cd $REPO && git remote get-url origin)"
  git config user.email bot@fomo; git config user.name fomo-server
  cd "$REPO"
fi
rm -rf "$STATE_WT"/state "$STATE_WT"/logs; mkdir -p "$STATE_WT/state" "$STATE_WT/logs"
cp state/*.json "$STATE_WT/state/" 2>/dev/null
for p in lloyd lab agresivo equilibrado tradicional; do [ -d state/plan_$p ] && mkdir -p "$STATE_WT/state/plan_$p" && cp state/plan_$p/*.json* "$STATE_WT/state/plan_$p/" 2>/dev/null; done
[ -f state/app/aplicaciones.jsonl ] && mkdir -p "$STATE_WT/state/app" && python3 -c "
import json,sys
for l in open('state/app/aplicaciones.jsonl'):
    d=json.loads(l); d.pop('ip',None); d.pop('email',None); print(json.dumps(d,ensure_ascii=False))
" > "$STATE_WT/state/app/aplicaciones.jsonl" 2>/dev/null
for f in trades closed signals outcomes; do [ -f state/$f.jsonl ] && tail -n 1500 state/$f.jsonl > "$STATE_WT/state/$f.jsonl"; done
cp -r state/ops "$STATE_WT/state/" 2>/dev/null
[ -d state/research ] && cp -r state/research "$STATE_WT/state/" 2>/dev/null
[ -d state/plan_lloyd ] && cp state/plan_lloyd/brain.json state/plan_lloyd/positions.json "$STATE_WT/state/plan_lloyd/" 2>/dev/null
mkdir -p "$STATE_WT/state/desk"; cp state/desk/brain.json state/desk/regime.json state/desk/radar.json state/desk/radar_pos.json state/desk/categories.json state/desk/postmortem.json "$STATE_WT/state/desk/" 2>/dev/null; tail -n 200 state/desk/radar_log.jsonl > "$STATE_WT/state/desk/radar_log.jsonl" 2>/dev/null; cp state/desk/floor.json state/desk/floor_pos.json state/desk/floor_closed.jsonl "$STATE_WT/state/desk/" 2>/dev/null; tail -n 300 state/desk/floor_log.jsonl > "$STATE_WT/state/desk/floor_log.jsonl" 2>/dev/null; cp state/desk/radar_closed.jsonl state/desk/kols.json state/desk/grid.json state/desk/grid_pos_lab.json state/desk/trend.json "$STATE_WT/state/desk/" 2>/dev/null; tail -n 300 state/desk/kols_log.jsonl > "$STATE_WT/state/desk/kols_log.jsonl" 2>/dev/null; tail -n 50 state/desk/brain_shadow.jsonl > "$STATE_WT/state/desk/brain_shadow.jsonl" 2>/dev/null
[ -f state/desk/scan4.json ] && python3 -c "import json;d=json.load(open('state/desk/scan4.json'));d.pop('all',None);json.dump(d,open('$STATE_WT/state/desk/scan4.json','w'))" 2>/dev/null
[ -f state/STOP ] && cp state/STOP "$STATE_WT/state/"
journalctl -u fomo-live --no-pager -n 300 > "$STATE_WT/logs/fomo-live.log" 2>/dev/null
tail -n 100 logs/sync.log > "$STATE_WT/logs/sync.log" 2>/dev/null; tail -n 50 logs/sync.err > "$STATE_WT/logs/sync.err" 2>/dev/null
cp logs/LAST.txt "$STATE_WT/logs/" 2>/dev/null; cp data/validation_summary.json "$STATE_WT/state/" 2>/dev/null
systemctl is-active fomo-live > "$STATE_WT/state/service.txt" 2>&1; date -u +%FT%TZ >> "$STATE_WT/state/service.txt"
cd "$STATE_WT" && git add -A && git commit -q -m "estado $(date -u +%FT%TZ)" >/dev/null 2>&1
timeout 90 git push -q -f origin server-state >> "$REPO/logs/sync.err" 2>&1 || true
