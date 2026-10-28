#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
timeout 900 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump
echo; echo "=== scan3 ==="
timeout 500 python3 -u -m fomo_intel.desk.scan3
