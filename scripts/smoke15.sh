#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
ffmpeg -loglevel error -f lavfi -i testsrc=s=320x180:r=25:d=1 -c:v libx264 -pix_fmt yuv420p "$tmp/clip.mp4"

t "JS: syntaxe" "for f in static/*.js; do node --check \$f || exit 1; done"
t "JS: settle après chaque lancement (4 onglets)" "[ \$(grep -c 'settle(' static/translate.js static/subs.js static/youtube.js static/app.js | awk -F: '{s+=\$2} END{print s}') -ge 5 ]"
t "JS: resync à l'ouverture SSE" "grep -q 'es.onopen = resync' static/app.js"

py - "$tmp" <<'PY'
import sys, os, time, asyncio, pathlib, zipfile, sqlite3
from atelier.config import cfg

d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(); (d / "out").mkdir()
cfg["desktop"]["notify"] = False
cfg["gpu"]["free_vram"] = False

from atelier import audio, convert, db, docs, epub, jobs
from atelier.jobs import register, manager
from fastapi.testclient import TestClient
from atelier.main import app, events

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

async def h_prog(ctx, p):
    for i in range(200):
        ctx.set(i / 200, f"étape {i}")
        await asyncio.sleep(0.001)
    ctx.set(1.0, "fin-msg")
async def h_trail(ctx, p):
    ctx.set(0.1, "debut")
    ctx.set(0.5, "mid")
    await asyncio.sleep(1.2)
register("t_prog", h_prog); register("t_trail", h_trail)

with TestClient(app, base_url="http://127.0.0.1:7777") as c:
    q = manager.subscribe()
    def submit(kind, **p):
        return c.post("/api/jobs", json={"kind": kind, "title": kind, "params": p}).json()["id"]
    def wait(jid, want=("done", "failed", "cancelled"), secs=30):
        for _ in range(secs * 20):
            j = next(x for x in c.get("/api/jobs").json() if x["id"] == jid)
            if j["status"] in want:
                return j
            time.sleep(0.05)
        raise SystemExit(f"timeout {jid}")

    # M8: coalescing + flush final
    j = wait(submit("t_prog"))
    n = q.qsize()
    check("M8: 200 set() -> peu d'événements SSE", n < 40)
    check("M8: message final conservé malgré la coalescence", j["message"] == "fin-msg" and j["progress"] == 1.0)
    jid = submit("t_trail")
    time.sleep(0.7)
    cur = next(x for x in c.get("/api/jobs").json() if x["id"] == jid)
    check("M8: flush différé (pas de dernière valeur perdue)", cur["message"] == "mid" and cur["status"] == "running")
    wait(jid)
    check("M8: WAL activé", sqlite3.connect(d / "data" / "atelier.db").execute("pragma journal_mode").fetchone()[0] == "wal")
    manager.unsubscribe(q)

    # M1: abonné trop lent -> flux terminé (le client se resynchronise)
    slow = manager.subscribe()
    for i in range(600):
        manager.emit("job", {"id": i})
    check("M1: abonné saturé marqué 'dropped'", slow in manager.dropped and slow not in manager.subs)
    # le générateur crée sa propre queue: on simule la saturation en la marquant
    async def run_stream():
        resp = await events()
        q2 = next(iter(manager.subs - {slow}))
        manager.dropped.add(q2)
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk)
        return out
    out = asyncio.run(asyncio.wait_for(run_stream(), 5))
    check("M1: flux SSE se termine pour un abonné dropped", len(out) <= 2)
    manager.unsubscribe(slow)

    # M5: sémaphore CPU avant verrou GPU
    convert._sem = asyncio.Semaphore(1)
    # le sémaphore vit dans la boucle du serveur (portail TestClient)
    c.portal.call(convert._sem.acquire)
    jid = submit("convert", path=str(d / "clip.mp4"), target="v:mp4-h264")
    time.sleep(1.0)
    j = next(x for x in c.get("/api/jobs").json() if x["id"] == jid)
    check("M5: job vidéo en attente du slot CPU ne tient PAS le verrou GPU", j["status"] == "running" and not manager.gpu_lock.locked())
    c.portal.call(lambda: convert._sem.release())
    check("M5: puis s'exécute et se termine", wait(jid, secs=60)["status"] in ("done", "failed"))

    from atelier.util import HEAVY
    c.portal.call(HEAVY.acquire)
    (d / "s.wav").write_bytes(b"x")
    cfg["audio"]["demucs_device"] = "cuda"
    cfg["audio"]["demucs_bin"] = "sh"
    jid = submit("audio", path=str(d / "s.wav"), action="stems")
    time.sleep(1.5)
    check("M5: demucs en attente de HEAVY ne tient pas le verrou GPU", not manager.gpu_lock.locked())
    c.post(f"/api/jobs/{jid}/cancel")
    c.portal.call(lambda: HEAVY.release())

# M9: la boucle n'est pas gelée par le parsing/écriture des gros documents
from docx import Document
big = d / "big.docx"
doc = Document()
for i in range(6000):
    doc.add_paragraph(f"Paragraph number {i} with some words to translate here.")
doc.save(big)

async def fake_tt(ctx, texts, src, tgt, glossary, lo, hi):
    await asyncio.sleep(0.01)
    return {t: "FR " + t for t in dict.fromkeys(texts)}
docs.translate_texts = fake_tt

class C:
    id = 1
    def set(self, *a, **k): pass
    def delta(self, t): pass

async def with_heartbeat(coro):
    gaps, stop = [], False
    async def beat():
        last = time.monotonic()
        while not stop:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
    t = asyncio.create_task(beat())
    await coro
    stop = True
    await t
    return max(gaps)

out_dir = d / "o"; out_dir.mkdir()
gap = asyncio.run(with_heartbeat(docs.do_office(C(), big, ".docx", "big", "en", "fr", [], out_dir)))
check(f"M9: docx 6000 paragraphes, boucle jamais bloquée > 0.5 s ({gap:.2f}s)", gap < 0.5 and (out_dir / "big.fr.docx").exists())

XH = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body>%s</body></html>'
cont = '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(250))
refs = "".join(f'<itemref idref="c{i}"/>' for i in range(250))
opf = f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>B</dc:title><dc:language>en</dc:language></metadata><manifest>{items}</manifest><spine>{refs}</spine></package>'
src = d / "big.epub"
with zipfile.ZipFile(src, "w") as z:
    z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
    z.writestr("META-INF/container.xml", cont); z.writestr("OEBPS/content.opf", opf)
    for i in range(250):
        z.writestr(f"OEBPS/c{i}.xhtml", XH % "".join(f"<p>Para {i}-{j} with <b>bold</b> and <i>italic</i> words here.</p>" for j in range(60)))
async def fake(texts):
    await asyncio.sleep(0.01)
    return {t: "FR " + t for t in dict.fromkeys(texts)}
dst = d / "big.fr.epub"
gap = asyncio.run(with_heartbeat(epub.translate_epub(src, dst, "fr", fake)))
check(f"M9: epub 250 chapitres, boucle jamais bloquée > 0.5 s ({gap:.2f}s)", gap < 0.5 and zipfile.ZipFile(dst).testzip() is None)
raise SystemExit(0 if ok else 1)
PY
t "phase 15 hors-ligne" "[ $? = 0 ]"
exit $fail
