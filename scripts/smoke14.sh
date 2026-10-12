#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# --- hors-ligne: vrai FastAPI (TestClient), vrais jobs
py - "$tmp" <<'PY'
import sys, os, time, asyncio, pathlib, signal
from atelier.config import cfg

d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data" / "tmp" / "leftover").mkdir(parents=True); (d / "out").mkdir()
cfg["desktop"]["notify"] = False

from atelier import db, jobs, proc, util
from atelier.jobs import register
from fastapi.testclient import TestClient
from atelier.main import app, purge_uploads

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

async def h_hold(ctx, p): await asyncio.sleep(1.0)
async def h_quick(ctx, p): return None
async def h_slow(ctx, p): await asyncio.sleep(60)
register("t_hold", h_hold); register("t_quick", h_quick); register("t_keep", h_quick, keep_uploads=True); register("t_slow", h_slow)

HOST = "http://127.0.0.1:7777"
with TestClient(app, base_url=HOST) as c:
    check("démarrage: data/tmp nettoyé", not (d / "data" / "tmp" / "leftover").exists())
    def upload(name="a.bin"):
        return c.post(f"/api/upload?name={name}", content=b"data").json()["path"]
    def submit(kind, **params):
        return c.post("/api/jobs", json={"kind": kind, "title": kind, "params": params}).json()["id"]
    def wait(jid, want=("done", "failed", "cancelled"), secs=15):
        for _ in range(secs * 20):
            j = next(x for x in c.get("/api/jobs").json() if x["id"] == jid)
            if j["status"] in want:
                return j
            time.sleep(0.05)
        raise SystemExit(f"timeout job {jid}")

    # H3: origine complète, port compris
    h = lambda **k: {"Origin": k.get("o"), **({"Sec-Fetch-Site": k["sf"]} if "sf" in k else {})} if k.get("o") else ({"Sec-Fetch-Site": k["sf"]} if "sf" in k else {})
    post = lambda **k: c.post("/api/jobs/clear", headers=h(**k)).status_code
    check("POST sans Origin (curl) accepté", post() == 200)
    check("POST même origine accepté", post(o=HOST) == 200)
    check("POST autre port local (Open WebUI) refusé", post(o="http://127.0.0.1:3000") == 403)
    check("POST localhost autre port refusé", post(o="http://localhost:3000") == 403)
    check("POST site distant refusé", post(o="https://evil.example") == 403)
    check("POST Origin null (iframe sandbox) refusé", post(o="null") == 403)
    check("POST https même hôte refusé", post(o="https://127.0.0.1:7777") == 403)
    check("Sec-Fetch-Site same-origin accepté", post(sf="same-origin") == 200)
    check("Sec-Fetch-Site same-site refusé (autre port)", post(sf="same-site") == 403)
    # B3: GET cross-site sur l'API refusé, page statique OK
    check("GET API cross-site refusé", c.get("/api/convert/catalog", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403)
    check("GET API same-origin accepté", c.get("/api/convert/catalog", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200)
    check("page statique cross-site (lien) accessible", c.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200)
    check("Host étranger refusé", TestClient(app, base_url="http://evil.example").get("/api/jobs").status_code == 403)

    # M3: chemins d'upload résolus et limités aux clés d'entrée
    root = d / "data" / "uploads"
    f = upload("x.bin")
    check("upload_paths: chemin direct", util.upload_paths({"path": f}) == [pathlib.Path(f).resolve()])
    check("upload_paths: '..' vers la base refusé", util.upload_paths({"path": f"{root}/../atelier.db"}) == [])
    check("upload_paths: clé inattendue ignorée", util.upload_paths({"x": f}) == [])
    (d / "outside").write_text("o"); (root / "link").symlink_to(d / "outside")
    check("upload_paths: symlink sortant refusé", util.upload_paths({"path": str(root / "link")}) == [])
    check("upload_paths: le dossier lui-même refusé", util.upload_paths({"path": str(root)}) == [])

    # H1: un upload partagé survit tant qu'un autre job l'utilise
    up = upload("shared.bin")
    a = submit("t_hold", path=up)
    b = submit("t_quick", path=up)
    wait(b)
    check("H1: job rapide fini, upload gardé (autre job actif)", pathlib.Path(up).exists())
    wait(a)
    check("H1: dernier job fini -> upload consommé", not pathlib.Path(up).exists())
    up = upload("keep.bin")
    wait(submit("t_keep", path=up))
    check("keep_uploads: upload conservé après succès", pathlib.Path(up).exists())

    # M10: purge par âge, hors fichiers utilisés par un job actif
    old, used, new = upload("old.bin"), upload("used.bin"), upload("new.bin")
    for p in (old, used):
        os.utime(p, (time.time() - 3 * 86400,) * 2)
    jid_active = db.insert("t_slow", "t", {"path": used}, False)
    purge_uploads()
    check("purge: vieux fichier supprimé", not pathlib.Path(old).exists())
    check("purge: fichier d'un job actif conservé", pathlib.Path(used).exists())
    check("purge: fichier récent conservé", pathlib.Path(new).exists())
    db.update(jid_active, status="done")

    # H2: l'arrêt annule les jobs en cours (les finally tournent)
    slow = submit("t_slow")
    wait(slow, want=("running",))

check("H2: arrêt -> job en cours marqué annulé", db.get(slow)["status"] == "cancelled")

# B2: callback qui lève -> enfant tué, pas orphelin
async def boom():
    pidf = d / "pid"
    def on_line(line): raise ValueError("callback")
    try:
        await proc.run_cmd(["sh", "-c", f"echo $$ > {pidf}; echo go; sleep 30"], on_line)
    except ValueError:
        return int(pidf.read_text())
pid = asyncio.run(boom())
time.sleep(0.2)
try:
    os.kill(pid, 0); alive = True
except ProcessLookupError:
    alive = False
check("B2: enfant tué si le callback lève", pid and not alive)

# M6 / M4: arguments des CLI
from atelier import convert
seen = []
async def fake_run(argv, *a, **k): seen.append(argv)
convert.need = lambda *a, **k: None
convert.run_cmd = fake_run
asyncio.run(convert.pandoc(pathlib.Path("/x/a.md"), pathlib.Path("/x/a.docx"), d))
check("M6: pandoc lecteur --sandbox puis écrivain filtré", len(seen) == 2 and "--sandbox" in seen[0] and "strip_images.lua" in " ".join(seen[1]))
check("M4: docs.py soffice avec profil dédié", "UserInstallation" in open("atelier/docs.py").read())
import importlib, shutil, zipfile
importlib.reload(convert)
if shutil.which("pandoc"):
    secret = d / "secret.png"; secret.write_bytes(b"\x89PNG\r\n\x1a\nSECRET-BYTES")
    md = d / "n.md"; md.write_text(f"# T\n\nHello ![alt text]({secret}) and ![remote](http://127.0.0.1:9/x.png) end\n")
    for out in ("docx", "epub", "html"):
        dst = d / f"n.{out}"
        try:
            asyncio.run(convert.pandoc(md, dst, d))
        except Exception as e:
            print("   err:", e)
        if out == "html":
            body = dst.read_text() if dst.exists() else "?"
            good = dst.exists() and "SECRET-BYTES" not in body and "alt text" in body and "<img" not in body
        else:
            z = zipfile.ZipFile(dst) if dst.exists() else None
            good = bool(z) and not any("media" in n for n in z.namelist()) and b"SECRET-BYTES" not in b"".join(z.read(n) for n in z.namelist())
        check(f"M6 réel: md -> {out} sans fichier local embarqué", good)
else:
    print("skip pandoc réel: sudo pacman -S pandoc-cli")
raise SystemExit(0 if ok else 1)
PY
t "phase 14 hors-ligne" "[ $? = 0 ]"

# --- live
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
t "service: Origin autre port refusé" "[ \$(code -X POST -H 'Origin: http://127.0.0.1:3000' $base/api/jobs/clear) = 403 ]"
t "service: Origin même origine accepté" "[ \$(code -H 'Origin: $base' $base/api/langs) = 200 ]"
t "service: GET API cross-site refusé" "[ \$(code -H 'Sec-Fetch-Site: cross-site' $base/api/langs) = 403 ]"
exit $fail
