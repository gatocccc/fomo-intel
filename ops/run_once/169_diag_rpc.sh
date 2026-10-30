#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "helius rpc:"; curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" -m 20 -X POST "https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY" -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
echo "rpc env:"; curl -s -m 20 -X POST "${SOLANA_RPC_URL:-https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY}" -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' | head -c 300; echo
echo "helius funded-by:"; curl -s -m 20 -w " %{http_code}\n" "https://api.helius.xyz/v1/wallet/G9DYnzG3tHPvuanEc4nB5qCj7TWYUPvv9gkib9sEahek/funded-by?api-key=$HELIUS_API_KEY" | head -c 300; echo
echo "solanatracker holders:"; curl -s -m 20 -o /dev/null -w "%{http_code}\n" -H "x-api-key: $SOLANATRACKER_API_KEY" "https://data.solanatracker.io/tokens/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz/holders/top"
echo "dd GTA6 (tope 300 s):"; time timeout 300 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 2>&1 | grep -v "^detalle" | tail -15
