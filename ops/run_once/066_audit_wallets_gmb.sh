#!/bin/bash
# Auditoría de billeteras del tweet de GMB_XBT (decu, zeropnl/wugi, sheep)
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 500 python3 -u -m fomo_intel.experiments.audit_wallets 9>&-
