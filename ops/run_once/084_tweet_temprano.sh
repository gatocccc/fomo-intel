#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 580 python3 -u -m fomo_intel.experiments.tweet_early 2>&1 | grep -v "^  tweet de\|^SIM\|^COMPRADOS\|^tweet NO\|^  tweet->\|^  herram\|^  autores\|^  mint sin\|^decu: seg"
