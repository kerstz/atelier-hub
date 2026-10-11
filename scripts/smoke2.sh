#!/usr/bin/env bash
set -u
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
post() { curl -fsS -X POST -H 'Content-Type: application/json' -d "${2-}" "$base$1"; }
state() { curl -fsS $base/api/jobs | jq_ "next(j['status'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 90); do s=$(state $1); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }

t "langs" "curl -fsS $base/api/langs | jq_ \"len(d)>5 and d[0]['code']=='auto'\" | grep -q True"
post /api/translations/clear '{}' >/dev/null

j=$(post /api/jobs '{"kind":"translate","title":"smoke","params":{"text":"The server is down.\n\nPlease restart the API.","src":"en","tgt":"fr","glossary":"API=interface"}}' | jq_ "d['id']")
t "translate done" "[ \$(wait_done $j) = done ]"
t "history" "curl -fsS $base/api/translations | jq_ \"len(d)==1 and len(d[0]['result'])>5\" | grep -q True"
curl -fsS $base/api/translations | jq_ "d[0]['result']"

long=$(python3 -c "print(('Long sentence number one. '*40+'\n\n')*6)")
j=$(post /api/jobs "{\"kind\":\"translate\",\"title\":\"cancel\",\"params\":{\"text\":$(python3 -c "import json,sys;print(json.dumps(sys.argv[1]))" "$long"),\"src\":\"en\",\"tgt\":\"fr\"}}" | jq_ "d['id']")
sleep 3
post /api/jobs/$j/cancel '{}' >/dev/null
t "cancel" "[ \$(wait_done $j) = cancelled ]"
t "gpu lock libéré" "curl -fsS $base/api/system | jq_ \"d['gpu_busy']\" | grep -q False"
exit $fail
