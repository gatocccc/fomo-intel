#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 500 python3 -u -m fomo_intel.desk.scan2
