#!/bin/bash
cd /root/fomo_intel
grep -c "^NONCO_CONTRACTS=." .env && grep "^NONCO_CONTRACTS=" .env | sed 's/=.*/=(cargada)/' || echo "NONCO_CONTRACTS no cargada"
curl -s 127.0.0.1:8770/api/admin/claves | python3 -c "import json,sys;[print(c['nombre'],c['cargada']) for c in json.load(sys.stdin)['claves']]"
