#!/usr/bin/env bash
set -u
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
post() { curl -sS -X POST -H 'Content-Type: application/json' -d "${2-}" "$base$1"; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 120); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }

t "probe url invalide" "post /api/youtube/probe '{\"url\":\"ftp://x\"}' | grep -q 'URL invalide'"
j=$(post /api/jobs '{"kind":"youtube","params":{"url":"file:///etc/passwd"}}' | jq_ "d['id']")
t "job url invalide échoue" "[ \$(wait_done $j) = failed ]"
j=$(post /api/jobs '{"kind":"youtube","params":{"url":"https://example.com/x","mode":"zip"}}' | jq_ "d['id']")
t "job mode invalide échoue" "[ \$(wait_done $j) = failed ]"
j=$(post /api/jobs '{"kind":"youtube","params":{"url":"https://example.com/x","quality":"1;rm"}}' | jq_ "d['id']")
t "job qualité invalide échoue" "[ \$(wait_done $j) = failed ]"

if curl -fsS --max-time 5 -o /dev/null https://www.youtube.com; then
  u=https://www.youtube.com/watch?v=jNQXAC9IVRw
  t "probe réseau" "post /api/youtube/probe '{\"url\":\"$u\"}' | jq_ \"d['playlist']==False and d['title']\" | grep -q -v False"
  for m in video audio; do
    j=$(post /api/jobs "{\"kind\":\"youtube\",\"params\":{\"url\":\"$u\",\"mode\":\"$m\",\"quality\":\"360\"}}" | jq_ "d['id']")
    t "download $m" "[ \$(wait_done $j) = done ]"
    o=$(job $j output)
    echo "     -> $o: $(ls -t "$o" | head -1)"
  done
else
  echo "skip tests réseau (pas d'accès youtube)"
fi
post /api/jobs/clear >/dev/null
exit $fail
