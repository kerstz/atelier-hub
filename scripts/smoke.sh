#!/usr/bin/env bash
set -u
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

t "index" "curl -fsS $base/ | grep -q Atelier"
t "static js" "curl -fsS $base/app.js | grep -q EventSource"
t "host étranger refusé" "[ \$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.com' $base/api/system) = 403 ]"
t "origin étranger refusé" "[ \$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: http://evil.com' $base/api/jobs/clear) = 403 ]"
t "system vram" "curl -fsS $base/api/system | jq_ \"d['vram']['total']>0\" | grep -q True"

post() { curl -fsS -X POST -H 'Content-Type: application/json' -d "${2-}" "$base$1"; }
state() { curl -fsS $base/api/jobs | jq_ "next(j['status'] for j in d if j['id']==$1)"; }

a=$(post /api/jobs '{"kind":"demo","params":{"gpu":true,"seconds":2}}' | jq_ "d['id']")
b=$(post /api/jobs '{"kind":"demo","params":{"gpu":true,"seconds":2}}' | jq_ "d['id']")
sleep 0.5
t "gpu lock: 2e job en file" "[ \$(state $b) = queued ]"
t "gpu lock: 1er job tourne" "[ \$(state $a) = running ]"
sleep 5
t "jobs terminés" "[ \$(state $a) = done ] && [ \$(state $b) = done ]"

c=$(post /api/jobs '{"kind":"demo","params":{"gpu":false,"seconds":30}}' | jq_ "d['id']")
sleep 0.5
post /api/jobs/$c/cancel >/dev/null
sleep 0.5
t "cancel" "[ \$(state $c) = cancelled ]"

t "sse" "timeout 2 curl -sN $base/api/events | grep -q retry"
post /api/jobs/clear '{}' >/dev/null
exit $fail
