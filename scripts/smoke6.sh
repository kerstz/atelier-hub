#!/usr/bin/env bash
set -u
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

list=$(curl -fsS $base/api/services)
t "liste non vide" "echo '$list' | python3 -c 'import sys,json; assert len(json.load(sys.stdin))>0'"
# état API == sonde bash indépendante
match=$(echo "$list" | python3 -c "
import sys,json,socket
for s in json.load(sys.stdin):
    c=socket.socket(); c.settimeout(1)
    up=c.connect_ex(('127.0.0.1',s['port']))==0
    print('ok' if up==s['up'] else 'bad', s['id'])
" | grep -c bad)
t "sonde == socket direct" "[ $match = 0 ]"
t "service inconnu 404" "[ \$(code -X POST $base/api/services/nope/start) = 404 ]"
t "action inconnue 404" "[ \$(code -X POST $base/api/services/\$(echo '$list' | python3 -c 'import sys,json; print(json.load(sys.stdin)[0][\"id\"])')/explode) = 404 ]"
t "sans commande -> 400" "[ \$(echo '$list' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(next((s[\"id\"] for s in d if not s[\"control\"]),\"\"))' | xargs -I{} curl -s -o /dev/null -w '%{http_code}' -X POST $base/api/services/{}/start) = 400 ]"
t "host étranger refusé" "[ \$(code -H 'Host: evil.com' $base/api/services) = 403 ]"
t "UI services.js" "curl -fsS $base/services.js | grep -q sv-list"
exit $fail
