#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
docs="$HOME/Atelier/docs"
fail=0
for _ in $(seq 30); do curl -fsS "$base/" >/dev/null 2>&1 && break; sleep 0.5; done
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 900); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }
# translate <file> [extra json] -> job id (file uploaded first)
submit() {
  up=$(curl -fsS -X POST --data-binary @"$1" "$base/api/upload?name=$(basename "$1")" | jq_ "d['path']")
  python3 -c "import json,sys; print(json.dumps({'kind':'document','title':'smoke','params':{'path':sys.argv[1],'src':'en','tgt':'fr',**json.loads(sys.argv[2] if len(sys.argv)>2 else '{}')}}))" "$up" "${2:-{\}}" \
    | curl -fsS -X POST -H 'Content-Type: application/json' -d @- $base/api/jobs | jq_ "d['id']"
}
py() { uv run --frozen --offline python "$@"; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"; rm -f "$docs"/smoke-doc*' EXIT
py - "$tmp" <<'PY'
import sys, docx, openpyxl
from pptx import Presentation
d = sys.argv[1]
doc = docx.Document()
doc.sections[0].header.paragraphs[0].text = "Internal report"
p = doc.add_paragraph(); r = p.add_run("The server is "); r2 = p.add_run("down"); r2.bold = True; p.add_run(" since this morning.")
doc.add_paragraph("Please restart the application and check the logs.")
tb = doc.add_table(rows=1, cols=2); tb.cell(0,0).text = "Name"; tb.cell(0,1).text = "Status"
doc.save(f"{d}/smoke-doc.docx")
prs = Presentation(); s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Quarterly results"; s.placeholders[1].text = "Revenue increased by ten percent."
prs.save(f"{d}/smoke-doc.pptx")
wb = openpyxl.Workbook(); ws = wb.active
ws["A1"] = "Customer"; ws["B1"] = "Amount"; ws["A2"] = "Good morning"; ws["B2"] = 42; ws["B3"] = "=B2*2"
wb.save(f"{d}/smoke-doc.xlsx")
PY
soffice --headless --convert-to odt --outdir "$tmp" "$tmp/smoke-doc.docx" >/dev/null 2>&1 && mv "$tmp/smoke-doc.odt" "$tmp/smoke-doc-legacy.odt"
soffice --headless --convert-to pdf --outdir "$tmp" "$tmp/smoke-doc.docx" >/dev/null 2>&1

j=$(submit "$tmp/smoke-doc.docx"); t "docx" "[ \$(wait_done $j) = done ]"
py - "$docs/smoke-doc.fr.docx" <<'PY' || fail=1
import sys, docx
d = docx.Document(sys.argv[1])
txt = [p.text for p in d.paragraphs]
print("    ", txt, d.sections[0].header.paragraphs[0].text, d.tables[0].cell(0,0).text)
assert len(txt) >= 2 and all("server" not in x.lower() for x in txt), "pas traduit"
assert d.paragraphs[0].runs, "runs perdus"
assert d.tables[0].cell(0,0).text.strip() not in ("", "Name")
assert d.sections[0].header.paragraphs[0].text not in ("", "Internal report")
PY
t "docx contenu" "[ \$? = 0 ]"

j=$(submit "$tmp/smoke-doc.pptx"); t "pptx" "[ \$(wait_done $j) = done ]"
py - "$docs/smoke-doc.fr.pptx" <<'PY'
import sys
from pptx import Presentation
s = Presentation(sys.argv[1]).slides[0]
t = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame]
print("    ", t)
assert t and all(x and "Quarterly" not in x and "Revenue" not in x for x in t)
PY
rc=$?; t "pptx contenu" "[ $rc = 0 ]"

j=$(submit "$tmp/smoke-doc.xlsx"); t "xlsx" "[ \$(wait_done $j) = done ]"
py - "$docs/smoke-doc.fr.xlsx" <<'PY'
import sys, openpyxl
ws = openpyxl.load_workbook(sys.argv[1]).active
print("    ", [c.value for r in ws.iter_rows() for c in r])
assert ws["A1"].value not in (None, "Customer") and ws["B2"].value == 42 and ws["B3"].value == "=B2*2"
PY
rc=$?; t "xlsx contenu (nombre + formule intacts)" "[ $rc = 0 ]"

j=$(submit "$tmp/smoke-doc-legacy.odt"); t "odt via LibreOffice" "[ \$(wait_done $j) = done ]"
t "odt -> docx traduit" "[ -f $docs/smoke-doc-legacy.fr.docx ]"

j=$(submit "$tmp/smoke-doc.pdf" '{"pages":"1"}'); r=$(wait_done $j)
t "pdf" "[ $r = done ]"
[ "$r" = done ] || echo "     $(job $j error) (pdf2zh_next --warmup fait ?)"
t "pdf mono" "ls $docs/smoke-doc*mono.pdf >/dev/null 2>&1"
t "pdf dual" "ls $docs/smoke-doc*dual.pdf >/dev/null 2>&1"
curl -fsS -X POST $base/api/jobs/clear >/dev/null
exit $fail
