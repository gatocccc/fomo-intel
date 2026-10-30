#!/bin/bash
cd /root/fomo_intel; set -a; . ./.env; set +a
echo "helius rpc:"; curl -s -m 20 -w " %{http_code}\n" -X POST "https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY" -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
echo "helius funded-by:"; curl -s -m 20 -w " %{http_code}\n" "https://api.helius.xyz/v1/wallet/G9DYnzG3tHPvuanEc4nB5qCj7TWYUPvv9gkib9sEahek/funded-by?api-key=$HELIUS_API_KEY" | head -c 300; echo
echo "=== anti-rug GTA6 + AGAIN ==="
time timeout 500 python3 -u -m fomo_intel.desk.dd 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz 7GWBnuU5ps1ZduiAsuKaYCehspfWWKZw69NF2E1xrZAA | grep -v "^detalle"
