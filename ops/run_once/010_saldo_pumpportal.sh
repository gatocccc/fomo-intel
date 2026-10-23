#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 -c "
from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print('PumpPortal wallet', Rpc(Env().rpc_url).sol_balance('FYxmJNnNs9fo9NhBX1GjbMNXF96KETTYCwxKXoFTcXan'), 'SOL')"
