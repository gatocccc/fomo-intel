#!/bin/bash
# 31/10 06:39: cargar la regla nueva del cerebro (ch6h ≥ −5% para candidatos de la lista).
cd /root/fomo_intel || exit 1
git log --oneline -1; grep -c '"min_ch6h": -0.05' fomo_intel/desk/brain.py
systemctl restart fomo-brain 2>&1; sleep 5; echo "fomo-brain: $(systemctl is-active fomo-brain)"
systemctl list-timers --no-pager 2>/dev/null | grep -i brain
