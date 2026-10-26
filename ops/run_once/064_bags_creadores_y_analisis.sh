#!/bin/bash
# Bags: creador real + historia previa (search creator=), socials "de verdad", y análisis. Pump: re-análisis con socials de verdad.
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 590 python3 -u -m fomo_intel.experiments.red fix_creators bags 9>&-
timeout 200 python3 -u -m fomo_intel.experiments.red analyze bags 9>&-
timeout 200 python3 -u -m fomo_intel.experiments.red analyze pump 9>&-
