#!/bin/bash
# Instala FOMO Intel en un servidor Linux (Debian/Ubuntu) y deja la validación corriendo cada 3 h.
# Uso: bash install_server.sh   (ejecutar dentro de la carpeta descomprimida ~/fomo_intel)
set -e
cd "$(dirname "$0")/.."
echo "== Python =="; python3 --version
python3 -m pip install --quiet --user requests 2>/dev/null || sudo apt-get install -y -q python3-requests
echo "== .env =="; [ -f .env ] || { echo "FALTA .env (copiarlo desde el Mac)"; exit 1; }
chmod 600 .env
mkdir -p logs data/charts data/launches
echo "== prueba sin red =="; python3 -m fomo_intel.cli report || true
echo "== cron cada 3 h =="
LINE="7 */3 * * * /bin/bash $HOME/fomo_intel/scripts/validate_cron.sh"
( crontab -l 2>/dev/null | grep -v validate_cron.sh ; echo "$LINE" ) | crontab -
crontab -l | grep validate_cron.sh
echo "== primera corrida (puede tardar 2-3 min) =="
BUDGET=600 bash scripts/validate_cron.sh && cat logs/LAST.txt
echo "LISTO"
