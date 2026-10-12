#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# --- B7: socket/lock privés, port lu dans config.toml
t "B7: sans XDG_RUNTIME_DIR -> dossier cache privé (pas /tmp)" "env -u XDG_RUNTIME_DIR XDG_CACHE_HOME=$tmp/cache bash scripts/atelier-desktop --dry-run | grep -qx socket=$tmp/cache/atelier/atelier-desktop.sock"
t "B7: dossier créé en 700" "[ \$(stat -c %a $tmp/cache/atelier) = 700 ]"
printf '[server]\nport = 9876\n' > "$tmp/c.toml"
t "B7: port lu dans config.toml" "env -u ATELIER_PORT ATELIER_CONFIG=$tmp/c.toml bash scripts/atelier-desktop --dry-run | grep -qx url=http://127.0.0.1:9876/"
t "B7: ATELIER_PORT prioritaire" "ATELIER_PORT=1234 ATELIER_CONFIG=$tmp/c.toml bash scripts/atelier-desktop --dry-run | grep -qx url=http://127.0.0.1:1234/"
printf 'pas du toml [[[' > "$tmp/bad.toml"
t "B7: config illisible -> 7777" "env -u ATELIER_PORT ATELIER_CONFIG=$tmp/bad.toml bash scripts/atelier-desktop --dry-run | grep -qx url=http://127.0.0.1:7777/"
t "B7: python fenêtre: même règle" "env -u XDG_RUNTIME_DIR XDG_CACHE_HOME=$tmp/c2 python3 -c \"import importlib.util as u; s=u.spec_from_file_location('w','scripts/atelier_desktop.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.runtime_dir())\" | grep -qx $tmp/c2/atelier"

# --- B9
t "B9: lxml déclaré" "grep -q '\"lxml' pyproject.toml"
t "B9: fastapi >= 0.143" "grep -q 'fastapi>=0.143' pyproject.toml"
t "B9: uv.lock à jour" "grep -q 'name = \"lxml\"' uv.lock"

py - "$tmp" <<'PY'
import sys, os, asyncio, pathlib, time, zipfile, subprocess, shutil
from atelier.config import cfg

d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(); (d / "out").mkdir()
cfg["desktop"]["notify"] = False

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

from atelier import docs, epub, notify, translate, util
from fastapi.testclient import TestClient
from atelier.main import app

# M7: segments plus longs que la limite découpés puis rejoints
class FakeTr:
    seen: list[int] = []
    def __init__(self, *a): pass
    def prompt(self, text): return text
    async def batch(self, items, prev):
        for _, t in items:
            FakeTr.seen.append(len(t))
        return {n: "FR:" + t for n, t in items}
docs.Translator = FakeTr
class Ctx:
    id = 1
    def set(self, *a, **k): pass
limit = int(cfg["translate"]["chunk_chars"])
long_text = " ".join(f"Sentence number {i} is here." for i in range(800))      # ~24 000 car.
res = asyncio.run(docs.translate_texts(Ctx(), [long_text, "short one"], "en", "fr", [], 0.0, 1.0))
check("M7: aucun lot > limite", FakeTr.seen and max(FakeTr.seen) <= limit)
check("M7: long segment rejoint, rien perdu", res[long_text].count("FR:") > 5 and "Sentence number 799 is here." in res[long_text])
check("M7: segment court inchangé", res["short one"] == "FR:short one")

# B8: base de nom libre
out = d / "o"; out.mkdir()
(out / "doc.fr.pdf").write_text("x"); (out / "doc (2).fr.pdf").write_text("x")
check("B8: free_base saute les noms pris", util.free_base("doc", lambda b: (out / f"{b}.fr.pdf").exists()) == "doc (3)")
check("B8: libre -> inchangé", util.free_base("new", lambda b: (out / f"{b}.fr.pdf").exists()) == "new")
src = "".join(open(f).read() for f in ("atelier/subs.py", "atelier/summary.py", "atelier/ocr.py", "atelier/docs.py"))
check("B8: subs/summary/ocr/docs utilisent free_base", src.count("free_base(") >= 4)

# B1: limites d'upload
with TestClient(app, base_url="http://127.0.0.1:7777") as c:
    up = d / "data" / "uploads"
    cfg["server"]["max_upload_mb"] = 1
    r = c.post("/api/upload?name=big.bin", content=b"x" * (2 << 20))
    check("B1: > limite -> 413, rien laissé", r.status_code == 413 and not list(up.iterdir()))
    def gen():
        for _ in range(8):
            yield b"x" * (512 << 10)
    r = c.post("/api/upload?name=stream.bin", content=gen())
    check("B1: flux sans Content-Length > limite -> 413, partiel supprimé", r.status_code == 413 and not list(up.iterdir()))
    r = c.post("/api/upload?name=ok.bin", content=b"x" * 1000)
    check("B1: sous la limite -> 200", r.status_code == 200 and len(list(up.iterdir())) == 1)
    cfg["server"]["min_free_gb"] = 10 ** 6
    r = c.post("/api/upload?name=full.bin", content=b"x" * 10)
    check("B1: disque insuffisant -> 507", r.status_code == 507 and len(list(up.iterdir())) == 1)

# B4: Ollama muet -> abandon avec message clair
async def silent_server():
    async def handle(r, w):
        await r.read(65536)
        await asyncio.sleep(30)
    return await asyncio.start_server(handle, "127.0.0.1", 0)
async def timeout_case():
    srv = await silent_server()
    cfg["ollama"]["url"] = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    cfg["ollama"]["timeout"] = 1
    t0 = time.monotonic()
    try:
        await translate.complete("m", [{"role": "user", "content": "x"}])
    except RuntimeError as e:
        return str(e), time.monotonic() - t0
    finally:
        srv.close()
msg, dt = asyncio.run(timeout_case())
check(f"B4: timeout de lecture ({dt:.1f}s) + message", "ne répond plus" in msg and dt < 5)

# B5: "--" avant le titre
bin_ = d / "bin"; bin_.mkdir()
stub = bin_ / "notify-send"
stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$NOTIFY_OUT"\n'); stub.chmod(0o755)
os.environ["PATH"] = f"{bin_}:{os.environ['PATH']}"; os.environ["NOTIFY_OUT"] = str(d / "n.txt")
cfg["desktop"]["notify"] = True
async def fire():
    notify.finished({"kind": "document", "title": "--evil-title", "status": "failed", "error": "--boom"}, {}, 10)
    await asyncio.sleep(0.4)
asyncio.run(fire())
args = (d / "n.txt").read_text().splitlines()
i = args.index("--")
check("B5: '--' avant titre et corps", args[i + 1] == "Échec : --evil-title" and args[-1] == "--boom")

# B6: EPUB bombe refusée vite, sans lecture complète
bomb = d / "bomb.epub"
with zipfile.ZipFile(bomb, "w") as z:
    z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
    z.writestr("META-INF/container.xml", "<x/>")
    z.writestr("OEBPS/huge.xhtml", b"\0" * (120 << 20), zipfile.ZIP_DEFLATED)
t0 = time.monotonic()
try:
    epub.load(bomb); err = ""
except RuntimeError as e:
    err = str(e)
check(f"B6: archive suspecte refusée ({time.monotonic() - t0:.1f}s)", "suspect" in err and time.monotonic() - t0 < 5)
big_part = d / "part.epub"
with zipfile.ZipFile(big_part, "w") as z:
    z.writestr("META-INF/container.xml", "<x/>" + " " * (70 << 20), zipfile.ZIP_STORED)
try:
    epub.load(big_part); err = ""
except RuntimeError as e:
    err = str(e)
check("B6: entrée XHTML/XML > 64 Mo refusée", "trop volumineux" in err)

raise SystemExit(0 if ok else 1)
PY
t "phase 16 hors-ligne" "[ $? = 0 ]"
exit $fail
