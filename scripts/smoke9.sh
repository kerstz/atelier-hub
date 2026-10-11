#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# --- hors-ligne: découpage transcript, prompts, détection couche texte
py - "$tmp" <<'PY'
import sys, asyncio, pathlib
from atelier import summary, srt, translate, ocr
from atelier.config import cfg

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

d = pathlib.Path(sys.argv[1])
raw = "".join(f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},900\nSentence number {i} of the talk.\n\n" for i in range(1, 400))
lines = summary.to_lines(srt.parse(raw))
check("lignes ~20 s horodatées", lines[0].startswith("[00:01] ") and len(lines) < 400 and lines[-1].startswith("[0"))
limit = (int(cfg["summary"]["num_ctx"]) - summary.RESERVE) * summary.CHARS_PER_TOKEN
big = lines * 30
parts = summary.group(big, limit)
check("map-reduce: plusieurs blocs", len(parts) > 1)
check("chaque bloc tient dans num_ctx", all(len(p) <= limit for p in parts))
check("aucune ligne perdue", sum(len(p.split("\n")) for p in parts) == len(big))
check("timestamps >1 h", summary.stamp("01:02:03,500") == "[1:02:03]")
fp = summary.final_prompt("French", "T", ("Résumé", "Points clés", "Chapitres"), False)
check("prompt final: 3 sections + timestamps", fp.count("## ") == 3 and "[timestamp]" in fp)
check("prompt image: cible + glossaire", "French" in translate.image_prompt("auto", "fr", [("a", "b")]) and "a = b" in translate.image_prompt("auto", "fr", [("a", "b")]))

def pdf(path, text):
    stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET" if text else ""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(stream)}>>\nstream\n{stream}\nendstream".encode(),
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{x}\n%%EOF\n".encode()
    path.write_bytes(out)

pdf(d / "text.pdf", "This page has a real text layer with enough characters to count.")
pdf(d / "blank.pdf", "")
check("has_text: PDF texte", asyncio.run(ocr.has_text(d / "text.pdf")) is True)
check("has_text: PDF sans texte", asyncio.run(ocr.has_text(d / "blank.pdf")) is False)
raise SystemExit(0 if ok else 1)
PY
t "hors-ligne" "[ $? = 0 ]"

# --- live
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 600); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }
upload() { curl -fsS -X POST --data-binary @"$1" "$base/api/upload?name=$(basename "$1")" | jq_ "d['path']"; }
newjob() { curl -fsS -X POST -H 'Content-Type: application/json' -d "$1" $base/api/jobs | jq_ "d['id']"; }
have_model() { curl -fsS -m 3 127.0.0.1:11434/api/tags 2>/dev/null | jq_ "any(m['name'].startswith('$1') for m in d['models'])" | grep -q True; }

# OCR : sans ocrmypdf -> échec explicite ; avec -> done
up=$(upload "$tmp/blank.pdf")
j=$(newjob "{\"kind\":\"ocr\",\"title\":\"smoke ocr\",\"params\":{\"path\":\"$up\"}}")
s=$(wait_done $j)
if command -v ocrmypdf >/dev/null; then
  t "ocr done" "[ $s = done ]"
  t "ocr sortie *.ocr.pdf" "ls \"$HOME/Atelier/docs\"/blank.ocr.pdf >/dev/null"
  rm -f "$HOME/Atelier/docs/blank.ocr.pdf"
else
  t "ocr sans ocrmypdf: échec explicite" "[ $s = failed ] && [ \"\$(job $j error | grep -c 'uv tool install ocrmypdf')\" = 1 ]"
fi

# Résumé d'un petit SRT (Ollama requis)
mdl=$(py -c "from atelier.config import cfg; print(cfg['summary']['model'] or cfg['ollama']['second_model'])")
if have_model "${mdl%%:*}"; then
  py - "$tmp/talk.srt" <<'PY'
import sys
t = ["Welcome to this talk about home gardening.", "First we cover soil preparation and compost.",
     "Then we talk about choosing seeds for spring.", "Watering should be done early in the morning.",
     "Finally we discuss pests and natural remedies.", "Thanks for watching, see you next time."]
open(sys.argv[1], "w").write("".join(
    f"{i}\n00:{i * 40 // 60:02d}:{i * 40 % 60:02d},000 --> 00:{i * 40 // 60:02d}:{i * 40 % 60:02d},900\n{x}\n\n" for i, x in enumerate(t)))
PY
  up=$(upload "$tmp/talk.srt")
  j=$(newjob "{\"kind\":\"summary\",\"title\":\"smoke résumé\",\"params\":{\"source\":\"$up\",\"src\":\"en\",\"lang\":\"fr\"}}")
  t "résumé done" "[ \$(wait_done $j) = done ]"
  curl -fsS $base/api/jobs/$j/result > "$tmp/res.md"
  t "résumé: 3 sections" "[ \$(grep -c '^## ' $tmp/res.md) -ge 3 ]"
  t "résumé: chapitres horodatés" "grep -Eq '\\[[0-9]{1,2}:[0-9]{2}' $tmp/res.md"
  rm -f "$HOME/Atelier/subs/talk.resume.md"
else
  echo "skip résumé: ollama pull $mdl"
fi

# Image -> vision -> traduction
vm=$(py -c "from atelier.config import cfg; print(cfg['ollama']['vision_model'])")
if have_model "${vm%%:*}"; then
  py - "$tmp/shot.png" <<'PY'
import sys
from PIL import Image, ImageDraw, ImageFont
im = Image.new("RGB", (900, 220), "white")
ImageDraw.Draw(im).text((30, 70), "Good morning, my friend", fill="black", font=ImageFont.load_default(size=56))
im.save(sys.argv[1])
PY
  up=$(upload "$tmp/shot.png")
  j=$(newjob "{\"kind\":\"translate\",\"title\":\"smoke image\",\"params\":{\"image\":\"$up\",\"src\":\"en\",\"tgt\":\"fr\"}}")
  t "image done" "[ \$(wait_done $j) = done ]"
  t "image traduite (bonjour)" "curl -fsS $base/api/translations | jq_ \"d[0]['result'].lower()\" | grep -Eq 'bonjour|salut'"
  t "upload image consommé" "[ ! -e \"$up\" ]"
else
  echo "skip image: ollama pull $vm"
fi
exit $fail
