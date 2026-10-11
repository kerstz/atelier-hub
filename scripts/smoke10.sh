#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# média de test
ffmpeg -loglevel error -f lavfi -i testsrc=s=640x360:r=25:d=2 -f lavfi -i sine=f=440:d=2 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$tmp/clip.mp4"
ffmpeg -loglevel error -f lavfi -i sine=f=440:d=2 "$tmp/tone.wav"
ffmpeg -loglevel error -f lavfi -i "color=c=red@0.5:s=1600x800,format=rgba" -frames:v 1 "$tmp/pic.png"
printf 'a,b\n1,2\n3,4\n' > "$tmp/t.csv"
printf '# Titre\n\nUn **gras** et un [lien](http://x.y).\n' > "$tmp/n.md"

# --- hors-ligne: EPUB inline-tag
py - "$tmp" <<'PY'
import re, sys, asyncio, pathlib, zipfile
from lxml import etree
from atelier import epub

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

d = pathlib.Path(sys.argv[1])
XH = '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><title>Chapter One</title></head><body>%s</body></html>'
ch1 = XH % ('<h1 id="c1">Hello world</h1><p>Plain <b>bold</b> and <i>italic</i> text with <a href="x.xhtml#a">a link</a>.</p>'
            '<p>Note<sup><a href="#n1" epub:type="noteref">1</a></sup> here<br/>next line <code>do_not_translate()</code></p>'
            '<pre>raw  code</pre><ul><li>Item <em>one</em><ul><li>Nested</li></ul></li></ul><p><img src="i.png" alt="x"/></p>')
nav = XH % '<nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter One</a></li><li><a href="ch2.xhtml">Chapter Two</a></li></ol></nav>'
ncx = '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap><navPoint id="n1"><navLabel><text>Chapter One</text></navLabel><content src="ch1.xhtml"/></navPoint></navMap></ncx>'
opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
       '<dc:identifier id="id">urn:x</dc:identifier><dc:title>My Book</dc:title><dc:creator>Jane Roe</dc:creator><dc:language>en</dc:language></metadata>'
       '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
       '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine><itemref idref="c1"/></spine></package>')
cont = '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
src = d / "b.epub"
with zipfile.ZipFile(src, "w") as z:
    z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
    z.writestr("META-INF/container.xml", cont)
    z.writestr("OEBPS/content.opf", opf); z.writestr("OEBPS/ch1.xhtml", ch1)
    z.writestr("OEBPS/nav.xhtml", nav); z.writestr("OEBPS/toc.ncx", ncx); z.writestr("OEBPS/i.png", b"\x89PNG")

calls = []
async def fake(texts):
    calls.append(list(texts))
    return {t: "FR " + t for t in dict.fromkeys(texts)}

dst = d / "b.fr.epub"
n = asyncio.run(epub.translate_epub(src, dst, "fr", fake))
check("runs extraits", n >= 6)
z = zipfile.ZipFile(dst)
check("mimetype premier + stocké", z.infolist()[0].filename == "mimetype" and z.infolist()[0].compress_type == 0)
check("png copié intact", z.read("OEBPS/i.png") == b"\x89PNG")
c = z.read("OEBPS/ch1.xhtml").decode()
root = etree.fromstring(c.encode())
ns = {"h": "http://www.w3.org/1999/xhtml"}
p = root.xpath("//h:p", namespaces=ns)[0]
check("XHTML bien formé + doctype", "<!DOCTYPE html>" in c)
check("gras/italique/lien conservés", p.xpath("count(h:strong|h:b)", namespaces=ns) == 1 and p.xpath("count(h:i|h:em)", namespaces=ns) == 1
      and p.xpath("h:a/@href", namespaces=ns) == ["x.xhtml#a"] )
check("texte traduit", "FR " in "".join(p.itertext()))
check("note de bas de page intacte", len(root.xpath("//h:sup/h:a[@href='#n1']", namespaces=ns)) == 1)
check("br + code intacts", len(root.xpath("//h:br", namespaces=ns)) == 1 and root.xpath("//h:code/text()", namespaces=ns) == ["do_not_translate()"])
check("pre inchangé", root.xpath("//h:pre/text()", namespaces=ns) == ["raw  code"])
check("img conservée", len(root.xpath("//h:img[@src='i.png']", namespaces=ns)) == 1)
check("liste imbriquée traduite", all("FR " in "".join(li.xpath("text()|em/text()")) for li in root.xpath("//h:li[h:ul]", namespaces=ns)))
check("lang html = fr", root.get("lang") == "fr")
check("title head traduit", root.xpath("//h:title/text()", namespaces=ns) == ["FR Chapter One"])
check("TOC nav traduite + lien", "FR Chapter Two" in z.read("OEBPS/nav.xhtml").decode() and 'href="ch1.xhtml"' in z.read("OEBPS/nav.xhtml").decode())
check("TOC ncx traduite", "FR Chapter One" in z.read("OEBPS/toc.ncx").decode())
o = z.read("OEBPS/content.opf").decode()
check("métadonnées: titre traduit, auteur/id gardés, langue fr", "FR My Book" in o and "Jane Roe" in o and "urn:x" in o and "<dc:language>fr</dc:language>" in o)

# repli: traducteur qui casse les balises -> texte plat, atomes préservés
async def bad(texts):
    return {t: "XX " + re.sub(r"<[^>]+>", "", t) for t in dict.fromkeys(texts)}
dst2 = d / "b2.epub"
asyncio.run(epub.translate_epub(src, dst2, "de", bad))
c2 = zipfile.ZipFile(dst2).read("OEBPS/ch1.xhtml").decode()
check("repli plat: atomes conservés", "do_not_translate()" in c2 and "<br" in c2 and "#n1" in c2)
raise SystemExit(0 if ok else 1)
PY
t "epub hors-ligne" "[ $? = 0 ]"

# --- hors-ligne: conversions réelles (appel direct)
py - "$tmp" <<'PY'
import sys, asyncio, pathlib, shutil, subprocess, os
from atelier import convert
from atelier.config import output_dir

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

class Ctx:
    id = 99910
    def set(self, *a, **k): pass

d = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[1]) / "out"
os.environ["HOME"] = str(d)
from atelier.config import cfg
cfg["paths"]["output"] = str(out)
cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(exist_ok=True)

def conv(name, target, **kw):
    try:
        r = asyncio.run(convert.run(Ctx(), {"path": str(d / name), "target": target, **kw}))
        return pathlib.Path(r)
    except Exception as e:
        print("   err:", e)
        return None

def probe(p):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,height", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.replace(",", " ").split()

det = asyncio.run(convert.detect(d / "clip.mp4"))
check("détection mp4 = video", det["category"] == "video" and any(t["id"] == "v:mkv-av1" for t in det["targets"]))
check("détection wav = audio", asyncio.run(convert.detect(d / "tone.wav"))["category"] == "audio")
check("détection inconnu = None", asyncio.run(convert.detect(d / "t.csv"))["category"] == "sheet")

r = conv("clip.mp4", "v:mkv-hevc")
check("vidéo HEVC (VAAPI ou CPU)", r and r.suffix == ".mkv" and "hevc" in probe(r))
r = conv("clip.mp4", "v:mp4-h264", size=180, quality="low")
check("vidéo h264 redim. 180p", r and "h264" in probe(r) and "180" in probe(r))
r = conv("clip.mp4", "v:mkv-av1")
check("vidéo AV1 libsvtav1 (CPU)", r and "av1" in probe(r))
r = conv("clip.mp4", "a:mp3")
check("audio extrait mp3", r and r.suffix == ".mp3" and "mp3" in probe(r))
r = conv("tone.wav", "a:opus")
check("wav -> opus", r and "opus" in probe(r))
r = conv("pic.png", "i:jpg")
check("png alpha -> jpg", r and "mjpeg" in probe(r) or (r and r.stat().st_size > 0))
r = conv("pic.png", "i:webp", size=400)
check("png -> webp redim. 400", r and r.is_file())
r = conv("pic.png", "i:png")
second = conv("pic.png", "i:avif")
check("noms uniques", len({p.name for p in out.joinpath("convert").iterdir()}) == len(list(out.joinpath("convert").iterdir())))
r = conv("clip.mp4", "i:png")
check("vidéo -> image refusé", r is None)
r = conv("t.csv", "d:pdf")
check("csv -> pdf (LibreOffice)", r and r.read_bytes()[:4] == b"%PDF")
if shutil.which("pandoc"):
    r = conv("n.md", "d:docx")
    check("md -> docx (pandoc)", r and r.read_bytes()[:2] == b"PK")
    r = conv("n.md", "d:pdf")
    check("md -> pdf (pandoc + LibreOffice)", r and r.read_bytes()[:4] == b"%PDF")
else:
    print("skip pandoc: sudo pacman -S pandoc-cli")
    check("md -> docx sans pandoc: échec explicite", conv("n.md", "d:docx") is None)
if not shutil.which("ebook-convert"):
    print("skip calibre: sudo pacman -S calibre")
raise SystemExit(0 if ok else 1)
PY
t "conversions" "[ $? = 0 ]"

# --- live
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
curl -fsS "$base/api/convert/catalog" >/dev/null 2>&1 || { echo "service sans phase 10: systemctl --user restart atelier"; exit 1; }
job() { curl -fsS $base/api/jobs | jq_ "next(j['$2'] for j in d if j['id']==$1)"; }
wait_done() { for _ in $(seq 300); do s=$(job $1 status); case $s in done|failed|cancelled) echo $s; return;; esac; sleep 1; done; echo timeout; }
upload() { curl -fsS -X POST --data-binary @"$1" "$base/api/upload?name=$(basename "$1")" | jq_ "d['path']"; }
newjob() { curl -fsS -X POST -H 'Content-Type: application/json' -d "$1" $base/api/jobs | jq_ "d['id']"; }

up=$(upload "$tmp/pic.png")
t "detect API" "curl -fsS -X POST -H 'Content-Type: application/json' -d '{\"path\":\"$up\"}' $base/api/convert/detect | jq_ \"d['category']\" | grep -q image"
j1=$(newjob "{\"kind\":\"convert\",\"title\":\"smoke img\",\"params\":{\"path\":\"$up\",\"target\":\"i:webp\"}}")
up=$(upload "$tmp/tone.wav")
j2=$(newjob "{\"kind\":\"convert\",\"title\":\"smoke audio\",\"params\":{\"path\":\"$up\",\"target\":\"a:flac\"}}")
t "job image done" "[ \$(wait_done $j1) = done ]"
t "job audio done" "[ \$(wait_done $j2) = done ]"
t "upload consommé" "[ ! -e \"$up\" ]"
t "download 1 fichier" "curl -fsS $base/api/jobs/$j1/download | head -c 4 | grep -q RIFF"
curl -fsS "$base/api/convert/zip?ids=$j1,$j2" -o "$tmp/z.zip"
t "zip 2 fichiers" "[ \$(unzip -l $tmp/z.zip | grep -c -E 'webp|flac') = 2 ]"
t "zip: ids vides -> 404" "[ \$(curl -s -o /dev/null -w '%{http_code}' \"$base/api/convert/zip?ids=999999\") = 404 ]"
for j in $j1 $j2; do rm -f "$(job $j output)"; done
exit $fail
