#!/bin/bash
# Corre la validación cada 3 h. Instalar con:  crontab -e  y pegar la línea de scripts/CRON.txt
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONWARNINGS="ignore"
# cargar claves del .env (cron no lee el perfil del shell)
set -a; [ -f .env ] && . ./.env; set +a
LOG="logs/validate_$(date +%Y%m%d_%H%M).log"
python3 -m fomo_intel.cli validate --budget "${BUDGET:-600}" > "$LOG" 2>&1
tail -1 "$LOG" > logs/LAST.txt
find logs -name 'validate_*.log' -mtime +14 -delete 2>/dev/null
