#!/usr/bin/env bash
# Phase 22 — Lecteur intégré: vrai ffmpeg, app FastAPI en process (TestClient), mpv factice.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/out/youtube" "$tmp/data" "$tmp/bin"
t "player.js: syntaxe" "node --check static/player.js"
t "UI: player.js chargé après app.js, bouton Lire" "grep -n 'player.js' static/index.html | grep -q . && grep -q openPlayer static/app.js"
cat > "$tmp/bin/mpv" <<'S'
#!/usr/bin/env bash
echo "mpv $*" >> "$FAKE_LOG"; exec sleep 1
S
chmod +x "$tmp/bin/mpv"
f="$tmp/out/youtube"
ffmpeg -loglevel error -f lavfi -i testsrc2=s=160x120:d=3 -f lavfi -i sine=f=440:d=3 -c:v libx264 -c:a aac -shortest -y "$f/ok h264.mp4"
ffmpeg -loglevel error -f lavfi -i testsrc2=s=160x120:d=3 -f lavfi -i sine=f=440:d=3 -c:v libvpx-vp9 -deadline realtime -c:a libopus -shortest -y "$f/clip vp9.mkv"
ffmpeg -loglevel error -f lavfi -i sine=f=300:d=3 -c:a libmp3lame -y "$f/son.mp3"
ffmpeg -loglevel error -f lavfi -i sine=f=300:d=3 -c:a pcm_s16le -y "$f/voix.wav"
printf '1\n00:00:00,500 --> 00:00:01,500\nBonjour\n\n' > "$f/clip vp9.fr.srt"
export FAKE_LOG="$tmp/log"; : > "$FAKE_LOG"
export ATELIER_TMP="$tmp"
PATH="$tmp/bin:$PATH" PYTHONPATH=. uv run --frozen --offline python - "$tmp" <<'PY'
import sys, os, pathlib, subprocess, time, json
from atelier.config import cfg
d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
cfg["player"]["mpv_bin"] = str(d / "bin/mpv")
from fastapi.testclient import TestClient
from atelier import main, db, media

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

def ffp(p, what):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", what, "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.split()

H = {"host": "127.0.0.1:7777"}
with TestClient(main.app, base_url="http://127.0.0.1:7777") as c:
    ids = {}
    for n in ("ok h264.mp4", "clip vp9.mkv", "son.mp3", "voix.wav"):
        j = db.insert("youtube", n, {}, False)
        db.update(j, status="done", output=str(d / "out/youtube" / n))
        ids[n] = j
    m = c.get(f"/api/jobs/{ids['ok h264.mp4']}/media?client=webkitgtk", headers=H).json()
    check("mp4 H.264/AAC: lisible tel quel, vidéo, prêt", m["native"] and m["kind"] == "video" and m["ready"] and not m["needs_prepare"])
    m = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/media?client=webkitgtk", headers=H).json()
    check("mkv VP9/Opus sur WebKitGTK: à préparer, sous-titre voisin listé", not m["native"] and m["needs_prepare"] and any(s["id"] == "x0" for s in m["subs"]))
    m2 = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/media?client=chromium", headers=H).json()
    check("mkv VP9/Opus sur Chromium: direct", m2["native"])
    check("mp3 et wav: audio, direct", all(c.get(f"/api/jobs/{ids[n]}/media", headers=H).json()["native"] for n in ("son.mp3", "voix.wav")))
    r = c.get(f"/api/jobs/{ids['ok h264.mp4']}/stream", headers={**H, "Range": "bytes=0-99"})
    check("stream: Range -> 206 + Content-Range", r.status_code == 206 and r.headers.get("content-range", "").startswith("bytes 0-99/") and len(r.content) == 100)
    r = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/stream", headers=H)
    check("stream non préparé -> 409", r.status_code == 409)
    r = c.post(f"/api/jobs/{ids['clip vp9.mkv']}/prepare?client=webkitgtk", headers=H).json()
    check("prepare lance une tâche preview", r.get("job"))
    for _ in range(120):
        row = db.get(r["job"])
        if row["status"] in ("done", "failed", "cancelled"): break
        time.sleep(0.5)
    check("préparation terminée", row["status"] == "done")
    m = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/media?client=webkitgtk", headers=H).json()
    r = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/stream?client=webkitgtk", headers=H)
    cached = next((d / "data/player-cache").glob("*.mp4"), None)
    check("mp4 en cache: prêt, H.264 + AAC, faststart", m["ready"] and r.status_code == 200 and cached and ffp(cached, "stream=codec_name") == ["h264", "aac"]
          and cached.read_bytes().find(b"moov") < cached.read_bytes().find(b"mdat"))
    r = c.post(f"/api/jobs/{ids['clip vp9.mkv']}/prepare?client=webkitgtk", headers=H).json()
    check("prepare déjà en cache -> ready sans nouvelle tâche", r == {"ready": True})
    r = c.get(f"/api/jobs/{ids['clip vp9.mkv']}/subs/x0.vtt", headers=H)
    check("sous-titre voisin .srt -> VTT (WEBVTT, point décimal)", r.text.startswith("WEBVTT") and "00:00:00.500 --> 00:00:01.500" in r.text)
    check("sous-titre inconnu -> 404", c.get(f"/api/jobs/{ids['clip vp9.mkv']}/subs/x9.vtt", headers=H).status_code == 404)
    # sécurité
    j = db.insert("youtube", "x", {}, False); db.update(j, status="done", output="/etc/passwd")
    check("fichier hors dossier de sortie -> 404", c.get(f"/api/jobs/{j}/stream", headers=H).status_code == 404)
    check("cross-site refusé (Sec-Fetch-Site)", c.get(f"/api/jobs/{ids['son.mp3']}/stream", headers={**H, "sec-fetch-site": "cross-site"}).status_code == 403)
    # mpv de repli
    r = c.post("/api/player/mpv", json={"id": ids["clip vp9.mkv"], "sub": "x0"}, headers=H)
    time.sleep(0.4)
    L = pathlib.Path(os.environ["FAKE_LOG"]).read_text()
    check("mpv de repli: lancé avec le fichier et le .srt voisin", r.status_code == 200 and "clip vp9.mkv" in L and "--sub-file=" in L)
    # cache
    for f in (d / "data/player-cache").iterdir():
        os.utime(f, (time.time() - 30 * 86400,) * 2)
    media.purge_cache()
    check("purge du cache (> cache_days)", not any((d / "data/player-cache").iterdir()))
sys.exit(0 if ok else 1)
PY
[ $? = 0 ] || fail=1
[ $fail = 0 ] && echo "smoke22 ok" || { echo "smoke22 ECHEC"; exit 1; }
