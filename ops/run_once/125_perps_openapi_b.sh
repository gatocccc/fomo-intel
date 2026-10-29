#!/bin/bash
# Baja la especificación OpenAPI de perps-api.jup.ag y resume rutas + campos de increase/decrease. Guarda el JSON en state/ops/perps_openapi.json.
cd /root/fomo_intel
for u in "https://perps-api.jup.ag/v1/docs/openapi.json" "https://perps-api.jup.ag/v1/docs/swagger.json" "https://perps-api.jup.ag/v1/docs/spec" "https://perps-api.jup.ag/v1/doc" "https://perps-api.jup.ag/openapi.json" "https://perps-api.jup.ag/v1/api-docs" "https://perps-api.jup.ag/v1/openapi.json" "https://perps-api.jup.ag/v1/docs/json" "https://perps-api.jup.ag/v1/docs"; do
  curl -s -m 20 "$u" -o /tmp/pdoc -w "$u [%{http_code}] "; head -c 120 /tmp/pdoc | tr '\n' ' '; echo
  python3 -c "import json;d=json.load(open('/tmp/pdoc'));assert d.get('paths')" 2>/dev/null && cp /tmp/pdoc state/ops/perps_openapi.json && break
done
curl -s -m 20 https://perps-api.jup.ag/v1/docs | grep -o "[a-zA-Z0-9_./:-]*\.json[a-zA-Z0-9_./?=-]*\|spec-url=\"[^\"]*\"\|url: *.[^,]*" | sort -u | head; curl -s -m 20 https://perps-api.jup.ag/v1/docs | head -c 1500
python3 - <<'PY'
import json,os
p='state/ops/perps_openapi.json'
if not os.path.exists(p): print('sin openapi'); raise SystemExit
d=json.load(open(p))
print('RUTAS:')
for path,ops in d.get('paths',{}).items():
    for m,o in ops.items(): print(f"  {m.upper():5s} {path}  — {o.get('summary') or o.get('operationId','')}")
def resolve(s,depth=0):
    if '$ref' in s:
        ref=s['$ref'].split('/')[1:]; x=d
        for k in ref: x=x[k]
        return resolve(x,depth)
    return s
def show(name,s,ind='    ',depth=0):
    s=resolve(s)
    if s.get('type')=='object' or 'properties' in s:
        for k,v in (s.get('properties') or {}).items():
            v=resolve(v); req=k in (s.get('required') or [])
            print(f"{ind}{k}{'*' if req else ''}: {v.get('type','')} {('enum='+str(v.get('enum'))) if v.get('enum') else ''} {v.get('description','')[:90]}")
            if depth<1 and (v.get('properties') or v.get('items')): show(k, v.get('items') or v, ind+'  ', depth+1)
    elif s.get('anyOf') or s.get('oneOf'):
        for alt in (s.get('anyOf') or s.get('oneOf')): show(name,alt,ind,depth)
for path,ops in d.get('paths',{}).items():
    if 'increase' in path or 'decrease' in path or 'execute' in path or 'send' in path or 'tpsl' in path:
        for m,o in ops.items():
            print(f"\n=== {m.upper()} {path}")
            rb=o.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
            if rb: print('  body:'); show('body',rb)
            for code,r in (o.get('responses') or {}).items():
                sc=r.get('content',{}).get('application/json',{}).get('schema')
                if sc and code.startswith('2'): print(f'  respuesta {code}:'); show('resp',sc)
PY
