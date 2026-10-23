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
export GIT_SSH_COMMAND="ssh -i /root/.ssh/fomo_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
mkdir -p state/ops logs

# ---- 1) código ----
git fetch -q origin main 2>>logs/sync.err || true
LOCAL=$(git rev-parse HEAD 2>/dev/null); REMOTE=$(git rev-parse origin/main 2>/dev/null)
if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
  CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE" 2>/dev/null)
  git reset -q --hard origin/main
  echo "$(date -u +%FT%TZ) actualizado $LOCAL -> $REMOTE" >> logs/sync.log
  if echo "$CHANGED" | grep -q '^requirements'; then python3 -m pip install -q --break-system-packages -r requirements.txt >> logs/sync.log 2>&1 || python3 -m pip install -q -r requirements.txt >> logs/sync.log 2>&1; fi
  if echo "$CHANGED" | grep -Eq '^(fomo_intel/live/|fomo_intel/backtest/rules.py|requirements)'; then
    systemctl restart fomo-live && echo "$(date -u +%FT%TZ) fomo-live reiniciado" >> logs/sync.log
  fi
  if echo "$CHANGED" | grep -q '^fomo_intel/live/control_server.py'; then systemctl restart fomo-control 2>/dev/null || true; fi
fi

# ---- 2) mantenimiento: scripts de una sola vez ----
touch state/ops/ran.txt
for f in ops/run_once/*.sh; do
  [ -f "$f" ] || continue
  id=$(basename "$f" .sh)
  grep -qx "$id" state/ops/ran.txt && continue
  echo "$id" >> state/ops/ran.txt
  { echo "== $id $(date -u +%FT%TZ) =="; timeout 600 bash "$f"; echo "== exit $? =="; } > "state/ops/$id.out" 2>&1
done

# ---- dashboard (cada minuto, barato: solo lee archivos) ----
[ -d /var/www/fomo ] && python3 -m fomo_intel.dashboard /var/www/fomo/index.html >> logs/dashboard.log 2>&1 || true

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
for f in trades closed signals; do [ -f state/$f.jsonl ] && tail -n 400 state/$f.jsonl > "$STATE_WT/state/$f.jsonl"; done
cp -r state/ops "$STATE_WT/state/" 2>/dev/null
[ -f state/STOP ] && cp state/STOP "$STATE_WT/state/"
journalctl -u fomo-live --no-pager -n 300 > "$STATE_WT/logs/fomo-live.log" 2>/dev/null
tail -n 100 logs/sync.log > "$STATE_WT/logs/sync.log" 2>/dev/null; tail -n 50 logs/sync.err > "$STATE_WT/logs/sync.err" 2>/dev/null
cp logs/LAST.txt "$STATE_WT/logs/" 2>/dev/null; cp data/validation_summary.json "$STATE_WT/state/" 2>/dev/null
systemctl is-active fomo-live > "$STATE_WT/state/service.txt" 2>&1; date -u +%FT%TZ >> "$STATE_WT/state/service.txt"
cd "$STATE_WT" && git add -A && git commit -q -m "estado $(date -u +%FT%TZ)" >/dev/null 2>&1
git push -q -f origin server-state >> "$REPO/logs/sync.err" 2>&1 || true
