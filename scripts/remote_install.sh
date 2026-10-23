#!/bin/bash
# Se ejecuta EN EL SERVIDOR (lo manda server_bootstrap.sh por ssh). Idempotente.
# Requiere: variables DEPLOY_KEY_B64 (clave privada del deploy key, base64) y REPO_SSH (git@github.com:owner/repo.git)
set -e
REPO=/root/fomo_intel
cd "$REPO"
echo "== deploy key =="
mkdir -p /root/.ssh; chmod 700 /root/.ssh
echo "$DEPLOY_KEY_B64" | base64 -d > /root/.ssh/fomo_deploy; chmod 600 /root/.ssh/fomo_deploy
ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null || true
export GIT_SSH_COMMAND="ssh -i /root/.ssh/fomo_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

echo "== git =="
if [ ! -d .git ]; then git init -q; fi
git config user.email bot@fomo; git config user.name fomo-server
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_SSH"
cat > .gitignore <<'EOF'
.env
.venv/
__pycache__/
*.pyc
data/
logs/
state/
secrets/
*.tgz
_to_delete/
EOF
# 1) foto de lo que hay HOY en el servidor (incluye el dashboard) -> rama server-snapshot
git add -A >/dev/null 2>&1 || true
git commit -q -m "snapshot servidor $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
git branch -f server-snapshot HEAD
git push -q -f origin server-snapshot
echo "snapshot publicado"
# 2) traer main y dejarlo como código vigente (los archivos no versionados: data, .env, state, quedan)
git fetch -q origin main
git checkout -q -B main origin/main
echo "main desplegado: $(git rev-parse --short HEAD)"

echo "== dependencias =="
python3 -m pip install -q --break-system-packages -r requirements.txt 2>/dev/null || python3 -m pip install -q -r requirements.txt
python3 -c "import solders, websocket, requests; print('deps ok')"

echo "== estado inicial =="
mkdir -p state secrets logs
chmod 700 secrets
[ -f state/control.json ] || python3 - <<'EOF'
from pathlib import Path
from fomo_intel.live.config import LiveParams
p = LiveParams(); p.mode = "paper"; p.save(Path("state"))
print("control.json creado en modo paper")
EOF
grep -q '^LIVE_MODE=' .env || echo 'LIVE_MODE=paper' >> .env
grep -q '^FOMO_STATE_DIR=' .env || echo 'FOMO_STATE_DIR=state' >> .env
grep -q '^FOMO_WALLET_FILE=' .env || echo 'FOMO_WALLET_FILE=secrets/wallet.json' >> .env

echo "== billetera del bot =="
python3 - <<'EOF'
import json, os
from pathlib import Path
from fomo_intel.live.wallet import load_or_create
kp = load_or_create(Path("secrets/wallet.json"))
print("direccion publica:", kp.pubkey())
json.dump({"pubkey": str(kp.pubkey())}, open("state/wallet_pub.json", "w"))
EOF

echo "== systemd =="
cat > /etc/systemd/system/fomo-live.service <<EOF
[Unit]
Description=FOMO Intel - bot en vivo
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO
EnvironmentFile=$REPO/.env
ExecStart=/usr/bin/python3 -m fomo_intel.live.bot
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q fomo-live
systemctl restart fomo-live
sleep 3; systemctl is-active fomo-live

echo "== cron =="
chmod +x scripts/*.sh
( crontab -l 2>/dev/null | grep -v server_sync.sh ; echo "* * * * * /bin/bash $REPO/scripts/server_sync.sh" ) | crontab -
crontab -l
echo "== primera publicación de estado =="
FORCE_STATE=1 bash scripts/server_sync.sh || true
echo "LISTO. Dirección de la billetera del bot: $(python3 -c 'import json;print(json.load(open("state/wallet_pub.json"))["pubkey"])')"
