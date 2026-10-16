#!/usr/bin/env bash
# Phase 25 — VERT: build monté sur /vert, hors-ligne, en-têtes, cadrage. Saute si le build est absent.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
B=http://127.0.0.1:7777
vert="$(python3 -c 'from atelier.config import data_dir; print(data_dir() / "vert")')"
t "build-vert.sh: syntaxe" "bash -n scripts/build-vert.sh"
t "vert.js: syntaxe" "node --check static/vert.js"
t "CSP /vert (même sans build)" "curl -sI $B/vert/ | grep -qi \"^content-security-policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' blob: data:; worker-src 'self' blob:\""
t "en-têtes anti-cadrage sur l'UI" "curl -sI $B/ | grep -qi '^x-frame-options: SAMEORIGIN' && curl -sI $B/ | grep -qi 'frame-ancestors'"
if [ ! -f "$vert/index.html" ]; then echo "skip VERT non construit ($vert): ./scripts/build-vert.sh"; exit $fail; fi
t "/vert/ 200 html" "curl -s -o /dev/null -w '%{http_code} %{content_type}' $B/vert/ | grep -q '^200 text/html'"
t "base /vert dans le HTML" "grep -q '/vert/_app/' $vert/index.html"
t "ffmpeg.wasm local" "curl -sf -o /dev/null $B/vert/ffmpeg/ffmpeg-core.wasm"
t "pas de service worker" "[ ! -f $vert/sw.js ]"
t "pas d'URL externe de service dans _app (vertd/jsdelivr ffmpeg)" "! grep -rqE 'vertd\\.vert\\.sh|cdn\\.jsdelivr\\.net/npm/@ffmpeg' $vert/_app"
t "licence + source" "[ -f $vert/LICENSE.VERT ] && grep -q AGPL $vert/SOURCE"
t "_app/immutable: cache long" "f=\$(cd $vert && ls _app/immutable/entry/*.js | head -1); curl -sI $B/vert/\$f | grep -qi 'max-age=31536000'"
t "HTML: no-cache" "curl -sI $B/vert/ | grep -qi 'cache-control: no-cache'"
t "traversal refusé" "[ \$(curl -s --path-as-is -o /dev/null -w '%{http_code}' $B/vert/../../etc/passwd) != 200 ]"
t "Host étranger refusé" "[ \$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.test' $B/vert/) = 403 ]"
exit $fail
