#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

t "JS: syntaxe" "for f in static/*.js; do node --check \$f || exit 1; done"
t "JS: barre de glossaires dans Traduire/Sous-titres/Documents" "[ \$(grep -c 'glossaryBar(\$gloss)' static/translate.js static/subs.js static/docs.js | awk -F: '{s+=\$2} END{print s}') -eq 3 ]"
t "UI: dépendances, disque, filtre, zone vocale" "grep -q 'id=\"deps\"' static/index.html && grep -q 'id=\"disk\"' static/index.html && grep -q 'tray-filter' static/index.html && grep -q 'id=\"sr-live\"' static/index.html"
t "UI: progressbar aria min/max/label" "grep -q 'aria-valuemax' static/ui.js"

py - "$tmp" <<'PY'
import sys, os, time, pathlib, asyncio
from atelier.config import cfg

d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(); (d / "out").mkdir()
cfg["desktop"]["notify"] = False
cfg["ollama"]["url"] = "http://127.0.0.1:9"          # injoignable
cfg["tts"]["bin"] = "piper-introuvable-xyz"
cfg["tts"]["voices_dir"] = str(d / "voices")
cfg["images"]["rembg_bin"] = "rembg-introuvable-xyz"

from atelier import db, translate
from fastapi.testclient import TestClient
from atelier.main import app

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

with TestClient(app, base_url="http://127.0.0.1:7777") as c:
    # --- dépendances
    rows = c.get("/api/deps").json()
    R = {r["id"]: r for r in rows}
    check("deps: champs id/label/ok/detail/hint/used_by", all({"id", "label", "ok", "detail", "hint", "used_by"} <= set(r) for r in rows))
    check("deps: ffmpeg présent, sans hint", R["ffmpeg"]["ok"] and R["ffmpeg"]["hint"] == "")
    check("deps: piper absent -> commande d'installation", not R["piper"]["ok"] and "uv tool install piper-tts" in R["piper"]["hint"])
    check("deps: rembg absent -> hint", not R["rembg"]["ok"] and "rembg" in R["rembg"]["hint"])
    check("deps: Ollama injoignable, pas de lignes modèle", not R["ollama"]["ok"] and not any(k.startswith("model-") for k in R))
    check("deps: voix fr absente -> commande de téléchargement", not R["voice-fr"]["ok"] and "download_voices" in R["voice-fr"]["hint"])

    # --- disque
    data = d / "data"
    up = data / "uploads"
    (up / "a.bin").write_bytes(b"x" * 5000); (up / "busy.bin").write_bytes(b"y" * 3000)
    logs = data / "logs"; logs.mkdir()
    (logs / "901.log").write_text("old"); (logs / "902.log").write_text("running")
    listen = d / "out" / "audio" / ".listen"; listen.mkdir(parents=True); (listen / "9.wav").write_bytes(b"w" * 100)
    (d / "out" / "docs").mkdir(exist_ok=True); (d / "out" / "docs" / "r.pdf").write_bytes(b"p" * 777)
    j_run = db.insert("t", "running job", {"path": str(up / "busy.bin")}, False)
    db.update(j_run, status="running")
    os.rename(logs / "902.log", logs / f"{j_run}.log")
    disk = c.get("/api/disk").json()
    I = {i["id"]: i for i in disk["items"]}
    check("disk: libre/total + postes", disk["free"] > 0 and disk["total"] >= disk["free"] and {"uploads", "logs", "listen", "tmp", "db", "out:docs"} <= set(I))
    check("disk: tailles", I["uploads"]["bytes"] == 8000 and I["out:docs"]["bytes"] == 777 and I["listen"]["bytes"] == 100)
    check("disk: sorties jamais nettoyables", not I["out:docs"]["clean"] and I["uploads"]["clean"])
    r = c.post("/api/disk/clean/uploads").json()
    check("disk: uploads vidés sauf fichier d'un job actif", r["freed"] == 5000 and (up / "busy.bin").exists() and not (up / "a.bin").exists())
    r = c.post("/api/disk/clean/logs").json()
    check("disk: journaux vidés sauf job actif", not (logs / "901.log").exists() and (logs / f"{j_run}.log").exists() and r["freed"] == 3)
    check("disk: lectures temporaires vidées", c.post("/api/disk/clean/listen").json()["freed"] == 100 and not (listen / "9.wav").exists())
    check("disk: cible inconnue / sortie -> 404", c.post("/api/disk/clean/out:docs").status_code == 404 and c.post("/api/disk/clean/etc").status_code == 404)
    check("disk: sortie intacte", (d / "out" / "docs" / "r.pdf").exists())
    db.update(j_run, status="done")

    # --- glossaires nommés
    check("gloss: liste vide", c.get("/api/glossaries").json() == [])
    check("gloss: PUT", c.put("/api/glossaries/Médecine (FR)", json={"text": "API=interface\nheart=cœur"}).status_code == 200)
    check("gloss: nom avec / refusé", c.put("/api/glossaries/a%2Fb", json={"text": "x"}).status_code in (400, 404, 405))
    check("gloss: nom avec ../ refusé", c.put("/api/glossaries/..%2Fx", json={"text": "x"}).status_code in (400, 404, 405))
    check("gloss: caractères interdits refusés (400)", c.put("/api/glossaries/a%3Bb%24", json={"text": "x"}).status_code == 400)
    check("gloss: rien stocké par les refus", [x["name"] for x in c.get("/api/glossaries").json()] == ["Médecine (FR)"])
    c.put("/api/glossaries/Médecine (FR)", json={"text": "heart=cœur"})
    g = c.get("/api/glossaries").json()
    check("gloss: mise à jour (upsert), un seul", len(g) == 1 and g[0]["text"] == "heart=cœur" and g[0]["name"] == "Médecine (FR)")
    ex = c.get("/api/glossaries/Médecine (FR)/export")
    check("gloss: export texte + nom de fichier", ex.status_code == 200 and ex.text == "heart=cœur" and "attachment" in ex.headers["content-disposition"])
    check("gloss: export inconnu 404", c.get("/api/glossaries/nope/export").status_code == 404)
    check("gloss: DELETE puis 404", c.delete("/api/glossaries/Médecine (FR)").status_code == 200 and c.delete("/api/glossaries/Médecine (FR)").status_code == 404)

    # --- fichier principal d'une tâche (chaînage)
    out = d / "out"
    (out / "subs").mkdir(exist_ok=True); (out / "youtube").mkdir(exist_ok=True)
    (out / "subs" / "clip.fr.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n")
    js = db.insert("subtitles", "sub", {}, False)
    db.update(js, status="done", output=str(out / "subs"), message="clip.fr.srt", started=time.time())
    r = c.get(f"/api/jobs/{js}/file")
    check("chaînage: sous-titres -> chemin du .srt", r.status_code == 200 and r.json()["name"] == "clip.fr.srt")
    old, new = out / "youtube" / "old.mp4", out / "youtube" / "new.mkv"
    old.write_bytes(b"o"); os.utime(old, (time.time() - 3600,) * 2); new.write_bytes(b"n")
    jy = db.insert("youtube", "yt", {}, False)
    db.update(jy, status="done", output=str(out / "youtube"), started=time.time() - 5)
    check("chaînage: youtube -> média le plus récent du job", c.get(f"/api/jobs/{jy}/file").json()["name"] == "new.mkv")
    jx = db.insert("subtitles", "evil", {}, False)
    db.update(jx, status="done", output="/etc", message="passwd.srt")
    check("chaînage: hors dossier de sortie -> 404", c.get(f"/api/jobs/{jx}/file").status_code == 404)
    jf = db.insert("youtube", "failed", {}, False)
    db.update(jf, status="failed", output=str(out / "youtube"))
    check("chaînage: tâche non terminée -> 404", c.get(f"/api/jobs/{jf}/file").status_code == 404)

# --- Traduire: contexte inter-blocs
seen = []
async def fake_chat(model, prompt=None, *, messages=None, options=None):
    seen.append(messages or [{"role": "user", "content": prompt}])
    yield f"TR{len(seen)}"
translate.stream_chat = fake_chat
class Ctx:
    id = 1
    def set(self, *a, **k): pass
    def delta(self, t): pass
db.init()
text = "\n\n".join(f"Paragraph {i}. " + "word " * 300 for i in range(3))   # 3 blocs de ~1500 car.
cfg["translate"]["chunk_chars"] = 1600
asyncio.run(translate.run(Ctx(), {"text": text, "src": "en", "tgt": "fr"}))
check("contexte: 1er bloc sans historique", len(seen[0]) == 1)
check("contexte: bloc 2 = (source, traduction) du bloc 1 + nouveau", len(seen[1]) == 3 and seen[1][1] == {"role": "assistant", "content": "TR1"} and "Paragraph 0" in seen[1][0]["content"])
check("contexte: seulement le bloc précédent (pas cumulatif)", len(seen[2]) == 3 and seen[2][1]["content"] == "TR2")
seen.clear(); cfg["translate"]["context"] = False
asyncio.run(translate.run(Ctx(), {"text": text, "src": "en", "tgt": "fr"}))
check("contexte: désactivable ([translate] context=false)", all(len(m) == 1 for m in seen) and len(seen) == 3)
raise SystemExit(0 if ok else 1)
PY
t "phase 18 hors-ligne" "[ $? = 0 ]"

# images sans libvips: repli ffmpeg (PATH ne contient que ffmpeg/ffprobe)
mkdir -p "$tmp/novips"; ln -sf "$(command -v ffmpeg)" "$tmp/novips/ffmpeg"; ln -sf "$(command -v ffprobe)" "$tmp/novips/ffprobe"
ffmpeg -loglevel error -y -f lavfi -i color=red:s=640x480 -frames:v 1 "$tmp/src.png"
cat > "$tmp/novips.py" <<'PY'
import asyncio, shutil, subprocess, sys
from pathlib import Path
from atelier import images
from atelier.convert import do_image
class Ctx:
    def set(self, *a, **k): pass
d = Path(sys.argv[1]); src = d / "src.png"
def dims(p): return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
assert shutil.which("vips") is None
for tgt, side, ext, want in (("i:jpg", 0, ".jpg", "640,480"), ("i:webp", 200, ".webp", "200,150"), ("i:png", 100, ".png", "100,75")):
    dest = d / f"out{tgt[2:]}{side}{ext}"; dest.touch()
    asyncio.run(do_image(Ctx(), src, tgt, dest, 1, side))
    assert dest.stat().st_size > 0 and dims(dest) == want, (tgt, dims(dest))
half = d / "half.png"; half.touch()
asyncio.run(images.half(src, half))
assert dims(half) == "320,240", dims(half)
try:
    asyncio.run(do_image(Ctx(), src, "i:avif", d / "x.avif", 1, 0)); raise SystemExit("avif sans vips: pas d'erreur")
except RuntimeError as e:
    assert "libvips" in str(e)
PY
if env PATH="$tmp/novips" PYTHONPATH=. "$(uv run --frozen --offline python -c 'import sys; print(sys.executable)')" "$tmp/novips.py" "$tmp" >"$tmp/novips.out" 2>&1; then echo "ok   images sans vips: jpg/webp/png/×2 via ffmpeg, avif exige vips"; else echo "FAIL images sans vips"; tail -5 "$tmp/novips.out"; fail=1; fi
exit $fail
