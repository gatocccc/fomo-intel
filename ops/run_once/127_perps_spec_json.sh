#!/bin/bash
cd /root/fomo_intel
python3 - <<'PY'
import re,json
h=open('state/ops/perps_docs.html').read()
i=h.rfind('<script>'); body=h[i+8:h.find('</script>',i)]
print('script tail len',len(body),'inicio:',body[:200].replace('\n',' '))
m=re.search(r'=\s*(\{.*\})\s*;?\s*$',body.strip(),re.S)
spec=None
if m:
    try:
        st=json.loads(m.group(1)); spec=(st.get('spec') or {}).get('data') or st.get('spec') or st
    except Exception as e: print('json error',e)
if not spec:
    # buscar el primer objeto que tenga "paths"
    j=body.find('"paths"'); k=body.rfind('{',0,j)
    print('fallback paths idx',j)
    raise SystemExit
json.dump(spec,open('state/ops/perps_openapi.json','w'))
d=spec; print('RUTAS:')
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
        print(f"\n=== {mth.upper()} {path}: {str(o.get('description',''))[:400]}")
        rb=(o.get('requestBody') or {}).get('content',{}).get('application/json',{}).get('schema')
        if rb: print('  body:'); show(rb)
        for code,r in (o.get('responses') or {}).items():
            sc=(r.get('content') or {}).get('application/json',{}).get('schema')
            if sc and str(code).startswith('2'): print(f'  respuesta {code}:'); show(sc)
PY
