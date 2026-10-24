#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
python3 -c "
import json; from fomo_intel.live.wallet import Rpc; from fomo_intel.live.config import Env
print('saldo bot', Rpc(Env().rpc_url).sol_balance(json.load(open('state/wallet_pub.json'))['pubkey']), 'SOL')"
