#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 300 python3 -u -m fomo_intel.desk.scan
