#!/usr/bin/env bash
set -u
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
subs="$HOME/Atelier/subs"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 600); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }
# submit <json params> -> job id
submit() { python3 -c "import json,sys; print(json.dumps({'kind':'subtitles','title':'smoke','params':json.loads(sys.argv[1])}))" "$1" \
  | curl -fsS -X POST -H 'Content-Type: application/json' -d @- $base/api/jobs | jq_ "d['id']"; }
cues() { grep -c -- '-->' "$1"; }
stamps() { grep -- '-->' "$1" | md5sum; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"; rm -f "$subs"/smoke-sub-test*' EXIT
python3 - "$tmp/smoke-sub-test.srt" <<'PY'
import sys
lines=["The server is down.","Please restart the API.","We will call you back tomorrow.","[Music]","Thank you for waiting."]
out=[]
for i in range(1,101):
    s=(i-1)*3; e=s+2
    f=lambda x:"00:%02d:%02d,000"%(x//60,x%60)
    out.append(f"{i}\n{f(s)} --> {f(e)}\n{lines[i%5]} ({i})\n")
open(sys.argv[1],"w").write("\n".join(out))
PY

j=$(submit "{\"source\":\"$tmp/smoke-sub-test.srt\",\"src\":\"en\",\"tgt\":\"fr\"}")
t "srt 100 cues traduit" "[ \$(wait_done $j) = done ]"
o="$subs/smoke-sub-test.fr.srt"
t "même nb de cues" "[ \$(cues $o) = 100 ]"
t "timestamps intacts" "[ \"\$(stamps $o)\" = \"\$(stamps $tmp/smoke-sub-test.srt)\" ]"
t "source .en.srt gardé" "[ -f $subs/smoke-sub-test.en.srt ]"
echo "     $(sed -n 3,4p "$o" | tr '\n' ' ')"

up=$(curl -fsS -X POST --data-binary @"$tmp/smoke-sub-test.srt" "$base/api/upload?name=smoke-up.srt" | jq_ "d['path']")
t "upload écrit" "[ -f '$up' ]"
j=$(submit "{\"source\":\"$up\",\"src\":\"en\",\"tgt\":\"fr\",\"translate\":false}")
t "srt sans traduction" "[ \$(wait_done $j) = done ]"
t "upload conservé (réutilisable pour Résumer/Générer, purge par âge)" "[ -f '$up' ]"; rm -f "$up"
rm -f "$subs"/smoke-up*

j=$(submit '{"source":"/nonexistent.mkv"}')
t "fichier absent échoue" "[ \$(wait_done $j) = failed ]"

mp3="$HOME/Atelier/youtube/Me at the zoo.mp3"
mkv="$HOME/Atelier/youtube/Me at the zoo.mkv"
if [ -f "$mkv" ]; then
  j=$(submit "$(python3 -c "import json,sys;print(json.dumps({'source':sys.argv[1],'src':'en','tgt':'fr','mux':True}))" "$mkv")")
  t "whisper + traduction + mux" "[ \$(wait_done $j) = done ]"
  t "srt fr" "[ \$(cues \"$subs/Me at the zoo.fr.srt\") -ge 3 ]"
  t "mkv sous-titré" "[ \$(ffprobe -v error -select_streams s -show_entries stream=index -of csv=p=0 \"$subs/Me at the zoo.fr.mkv\" | wc -l) -ge 1 ]"
  cat "$subs/Me at the zoo.fr.srt" | sed -n 1,8p
else
  echo "skip whisper/mux (lance smoke3.sh d'abord pour avoir le mkv test)"
fi
curl -fsS -X POST $base/api/jobs/clear >/dev/null
exit $fail
