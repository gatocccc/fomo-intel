#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import json
h=open('state/ops/perps_docs.html').read()
i=h.find('const __redoc_state = ')+len('const __redoc_state = ')
st,_=json.JSONDecoder().raw_decode(h[i:]); spec=st['spec']['data']
if isinstance(spec,str): spec=json.loads(spec)
print('tipo',type(spec).__name__, list(spec)[:6] if isinstance(spec,dict) else spec[:200])
json.dump(spec,open('state/ops/perps_openapi.json','w'))
d=spec
for path,ops in d.get('paths',{}).items():
    for mth,o in ops.items(): print(f"  {mth.upper():5s} {path}  — {o.get('summary') or o.get('operationId','')}")
def resolve(s):
    while isinstance(s,dict) and '$ref' in s:
        x=d
        for kk in s['$ref'].split('/')[1:]: x=x[kk]
        s=x
    return s
def show(s,ind='    ',depth=0):
    s=resolve(s)
    for alt in (s.get('anyOf') or s.get('oneOf') or s.get('allOf') or []): show(alt,ind,depth)
    for kk,v in (s.get('properties') or {}).items():
        v=resolve(v); req=kk in (s.get('required') or [])
        print(f"{ind}{kk}{'*' if req else ''}: {v.get('type','')} {('enum='+str(v.get('enum'))) if v.get('enum') else ''} {str(v.get('description',''))[:110]}")
        if depth<2 and (v.get('properties') or v.get('items') or v.get('anyOf')): show(v.get('items') or v, ind+'  ', depth+1)
for path,ops in d.get('paths',{}).items():
    for mth,o in ops.items():
        if mth.lower()!='post': continue
        print(f"\n=== {mth.upper()} {path}: {str(o.get('description',''))[:500]}")
        rb=(o.get('requestBody') or {}).get('content',{}).get('application/json',{}).get('schema')
        if rb: print('  body:'); show(rb)
        for code,r in (o.get('responses') or {}).items():
            sc=(r.get('content') or {}).get('application/json',{}).get('schema')
            if sc and str(code).startswith('2'): print(f'  respuesta {code}:'); show(sc)
PY
