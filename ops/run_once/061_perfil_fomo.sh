#!/bin/bash
# Buscar la wallet del perfil FOMO "KmanuS88" (fomo.family) para auditar sus llamadas.
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
D=/tmp/fomo061; mkdir -p $D
for u in "https://fomo.family/KmanuS88" "https://fomo.family/@KmanuS88" "https://fomo.family/kmanus88" "https://fomo.family/profile/KmanuS88" "https://fomo.family/u/KmanuS88" "https://fomo.family/user/KmanuS88" "https://fomo.family"; do
  f=$D/$(echo "$u" | md5sum | cut -c1-8).html
  code=$(curl -sL -A "$UA" -o $f -w "%{http_code} %{url_effective}" --max-time 20 "$u")
  echo "== $u -> $code bytes=$(wc -c <$f)"
  grep -oE '<title>[^<]*' $f | head -2
  grep -oE '[1-9A-HJ-NP-Za-km-z]{32,44}' $f | sort | uniq -c | sort -rn | head -8
  grep -oiE '.{0,80}kmanus.{0,120}' $f | head -5
  grep -oE 'https?://[a-zA-Z0-9.-]*(api|backend|graphql)[a-zA-Z0-9./_-]*' $f | sort -u | head -10
done
echo "== scripts del home"
f=$D/home.html; curl -sL -A "$UA" --max-time 20 https://fomo.family -o $f
for s in $(grep -oE '(src|href)="[^"]*\.js[^"]*"' $f | cut -d'"' -f2 | head -15); do
  case $s in http*) url=$s;; *) url="https://fomo.family$s";; esac
  curl -sL --max-time 20 "$url" -o $D/s.js
  grep -oE 'https?://[a-zA-Z0-9.-]+(\.[a-z]+)+(/[a-zA-Z0-9_/{}.:-]*)?' $D/s.js | grep -viE 'w3.org|github|reactjs|mozilla|google|sentry|apple|schema' | sort -u | head -25
  grep -oE '"/(api|v1|v2)/[a-zA-Z0-9_/{}:.-]*' $D/s.js | sort -u | head -30
done
