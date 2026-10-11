#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
docs="$HOME/Atelier/docs"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }

# --- hors-ligne: balises inline, reconstruction docx/pptx, progression pdf, whisper -l
py - <<'PY'
import tempfile, pathlib, asyncio, docx, docx.opc.constants as K
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx import Presentation
from atelier import inline, office, docs, subs
from atelier.config import cfg
from atelier.inline import Fmt

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

L = frozenset({1})
check("decode valide", inline.decode("a <b>b</b> <a1><i>c</i></a1>", L) is not None)
check("decode refuse", all(inline.decode(s, L) is None for s in ["<b>x", "x</b>", "<a2>x</a2>", "<b><i>x</i></b", "a<br>b", "<b></b>"]))
check("encode 1 format = None", inline.encode([("a", Fmt(b=True)), (" b", Fmt(b=True))]) is None)

d = pathlib.Path(tempfile.mkdtemp())
doc = docx.Document(); p = doc.add_paragraph()
p.add_run("The server is "); p.add_run("down").bold = True; p.add_run(" see ")
rid = doc.part.relate_to("https://example.org", K.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
h = OxmlElement("w:hyperlink"); h.set(qn("r:id"), rid)
r = OxmlElement("w:r"); t = OxmlElement("w:t"); t.text = "the docs"; r.append(t); h.append(r); p._p.append(h)
doc.save(d / "a.docx")
slots, save = office.LOADERS[".docx"](d / "a.docx")
s = slots[0]
check("docx tagué", s.tagged == "The server is <b>down</b> see <a1>the docs</a1>")
s.put_segs(inline.decode("Le serveur est <b>en panne</b>, voir <a1>la doc</a1>", s.links)); save(d / "b.docx")
q = docx.Document(str(d / "b.docx")).paragraphs[0]
check("docx gras gardé", [(x.text, x.bold) for x in q.runs] == [("Le serveur est ", None), ("en panne", True), (", voir ", None)])
check("docx lien gardé", q._p.xml.count("<w:hyperlink") == 1 and "la doc" in q.text)

prs = Presentation(); sl = prs.slides.add_slide(prs.slide_layouts[1])
para = sl.placeholders[1].text_frame.paragraphs[0]
a = para.add_run(); a.text = "Revenue is "; b = para.add_run(); b.text = "up"; b.font.bold = True
c = para.add_run(); c.text = " see site"; c.hyperlink.address = "https://example.org"; c.font.italic = True
prs.save(d / "a.pptx")
slots, save = office.LOADERS[".pptx"](d / "a.pptx")
s = next(x for x in slots if x.tagged)
s.put_segs(inline.decode("Le revenu est <b>en hausse</b>, voir <a1><i>le site</i></a1>", s.links)); save(d / "b.pptx")
runs = Presentation(str(d / "b.pptx")).slides[0].placeholders[1].text_frame.paragraphs[0].runs
check("pptx gras/italique/lien", [(r.text, r.font.bold, r.font.italic, r.hyperlink.address) for r in runs][1:] ==
      [("en hausse", True, None, None), (", voir ", None, None, None), ("le site", None, True, "https://example.org")])

got = []
class C:
    def set(self, p=None, message=None): got.append(p)
f = docs.pdf_progress(C())
f("\x1b[2Ktranslate \x1b[38;5;197m━━━━╸━━\x1b[0m 45/100 0:00:12 0:00:20")
f("translate                                            45/100 0:00:12 0:00:20")
f("Parse PDF (1/1)                                    3/10 0:00:01")
check("pdf progression 45 %", 0.45 in got)

seen = []
async def fake(argv, on_line=None, **kw): seen.append(argv)
subs.run_cmd, subs.shutil.which = fake, lambda _: "x"
mdl = d / "m.bin"; mdl.write_text("x"); cfg["whisper"]["model"] = str(mdl)
class Ctx:
    def set(self, *a, **k): pass
for lang in ("fr", "auto"):
    asyncio.run(subs.transcribe(Ctx(), d / "x.mp3", lang, d, 0, 1))
wh = [a for a in seen if "-l" in a]
check("whisper -l fr puis auto", [a[a.index("-l") + 1] for a in wh] == ["fr", "auto"])
raise SystemExit(0 if ok else 1)
PY
t "hors-ligne" "[ $? = 0 ]"

# --- live (Ollama + service requis)
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 900); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }
submit() {
  up=$(curl -fsS -X POST --data-binary @"$1" "$base/api/upload?name=$(basename "$1")" | jq_ "d['path']")
  python3 -c "import json,sys; print(json.dumps({'kind':'document','title':'smoke','params':{'path':sys.argv[1],'src':'en','tgt':'fr'}}))" "$up" \
    | curl -fsS -X POST -H 'Content-Type: application/json' -d @- $base/api/jobs | jq_ "d['id']"
}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"; rm -f "$docs"/smoke-fmt*' EXIT
py - "$tmp" <<'PY'
import sys, docx
doc = docx.Document(); p = doc.add_paragraph()
p.add_run("The server is "); p.add_run("down").bold = True; p.add_run(" since "); p.add_run("this morning").italic = True; p.add_run(".")
doc.add_paragraph("Please restart the application and check the logs. " * 40)
doc.save(sys.argv[1] + "/smoke-fmt.docx")
PY
soffice --headless --convert-to pdf --outdir "$tmp" "$tmp/smoke-fmt.docx" >/dev/null 2>&1

j=$(submit "$tmp/smoke-fmt.docx"); t "docx live" "[ \$(wait_done $j) = done ]"
py - "$docs/smoke-fmt.fr.docx" <<'PY'
import sys, docx
r = docx.Document(sys.argv[1]).paragraphs[0].runs
print("    ", [(x.text, x.bold, x.italic) for x in r])
assert any(x.bold and x.text.strip() for x in r) and any(x.italic and x.text.strip() for x in r), "format perdu (fallback ?)"
PY
t "docx gras+italique gardés" "[ \$? = 0 ]"

j=$(submit "$tmp/smoke-fmt.pdf")
mx=0
for _ in $(seq 900); do
  s=$(job $j status); p=$(job $j progress)
  [ "$s" = running ] && mx=$(python3 -c "print(max($mx, $p))")
  case $s in done|failed|cancelled) break;; esac; sleep 1
done
t "pdf done" "[ $s = done ]"
t "pdf progression réelle (max=$mx)" "python3 -c 'import sys; sys.exit(0 if 0 < $mx < 1 else 1)'"
exit $fail
