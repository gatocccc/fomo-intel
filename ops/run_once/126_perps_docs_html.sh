#!/bin/bash
cd /root/fomo_intel
curl -s -m 30 https://perps-api.jup.ag/v1/docs -o state/ops/perps_docs.html; ls -la state/ops/perps_docs.html
python3 - <<'PY'
import re,json
h=open('state/ops/perps_docs.html').read()
m=re.search(r'__redoc_state\s*=\s*(\{.*?\});?\s*</script>',h,re.S)
if not m:
    print('sin __redoc_state; scripts:', re.findall(r'<script[^>]*>',h)[:6]); raise SystemExit
st=json.loads(m.group(1)); spec=st.get('spec',{}).get('data') or st.get('spec')
json.dump(spec,open('state/ops/perps_openapi.json','w'))
d=spec; print('RUTAS:')
for path,ops in d.get('paths',{}).items():
    for mth,o in ops.items(): print(f"  {mth.upper():5s} {path}  — {o.get('summary') or o.get('operationId','')}")
def resolve(s):
    while isinstance(s,dict) and '$ref' in s:
        x=d
        for k in s['$ref'].split('/')[1:]: x=x[k]
        s=x
    return s
def show(s,ind='    ',depth=0):
    s=resolve(s)
    for alt in (s.get('anyOf') or s.get('oneOf') or s.get('allOf') or []): show(alt,ind,depth)
    for k,v in (s.get('properties') or {}).items():
        v=resolve(v); req=k in (s.get('required') or [])
        print(f"{ind}{k}{'*' if req else ''}: {v.get('type','')} {('enum='+str(v.get('enum'))) if v.get('enum') else ''} {str(v.get('description',''))[:100]}")
        if depth<2 and (v.get('properties') or v.get('items') or v.get('anyOf')): show(v.get('items') or v, ind+'  ', depth+1)
for path,ops in d.get('paths',{}).items():
    for mth,o in ops.items():
        if mth.lower()!='post' and 'position' not in path: continue
        print(f"\n=== {mth.upper()} {path}: {o.get('description','')[:300]}")
        rb=(o.get('requestBody') or {}).get('content',{}).get('application/json',{}).get('schema')
        if rb: print('  body:'); show(rb)
        for code,r in (o.get('responses') or {}).items():
            sc=(r.get('content') or {}).get('application/json',{}).get('schema')
            if sc and str(code).startswith('2'): print(f'  respuesta {code}:'); show(sc)
PY
