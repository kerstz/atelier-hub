#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/voices"

# --- faux binaires (valident la plomberie, pas les modèles)
cat > "$tmp/bin/piper" <<'S'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case $1 in -f) out=$2; shift;; -m) m=$2; shift;; esac; shift; done
[ -f "$m" ] || exit 3
txt=$(cat); [ -n "$txt" ] || exit 4
ffmpeg -loglevel error -f lavfi -i sine=f=300:d=1 -y "$out"
S
cat > "$tmp/bin/realesrgan" <<'S'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case $1 in -i) i=$2; shift;; -o) o=$2; shift;; -n) n=$2; shift;; -s) s=$2; shift;; esac; shift; done
echo "50.00%"; echo "100.00%"
echo "$n $s" > "$(dirname "$o")/args"
VIPS_WARNING=0 vips resize "$i" "$o" 4
S
cat > "$tmp/bin/rembg" <<'S'
#!/usr/bin/env bash
[ "$1" = i ] && cp "$4" "$5"
S
cat > "$tmp/bin/deepfilter" <<'S'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case $1 in -o) d=$2; shift;; *) f=$1;; esac; shift; done
cp "$f" "$d/$(basename "$f")"
S
cat > "$tmp/bin/demucs" <<'S'
#!/usr/bin/env bash
two=0; while [ $# -gt 0 ]; do case $1 in -n) n=$2; shift;; -o) o=$2; shift;; --two-stems) two=1; shift;; --mp3|--flac|--int24|--mp3-bitrate) [ "$1" = --mp3-bitrate ] && shift;; *) f=$1;; esac; shift; done
d="$o/$n/$(basename "$f" .wav)"; mkdir -p "$d"
echo "10%"; echo "100%"
if [ $two = 1 ]; then set -- vocals no_vocals; else set -- vocals drums bass other; fi
for s in "$@"; do ffmpeg -loglevel error -f lavfi -i sine=f=200:d=1 -y "$d/$s.mp3"; done
S
cat > "$tmp/bin/whisper" <<'S'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case $1 in -of) of=$2; shift;; esac; shift; done
echo " bonjour [BLANK_AUDIO] tout le monde" > "$of.txt"
S
chmod +x "$tmp/bin/"*
: > "$tmp/voices/fr_FR-siwis-medium.onnx"; : > "$tmp/whisper.bin"

ffmpeg -loglevel error -f lavfi -i "testsrc=s=64x48:d=1" -frames:v 1 "$tmp/in.png"
ffmpeg -loglevel error -f lavfi -i sine=f=440:d=2 "$tmp/song.wav"

# --- hors-ligne
py - "$tmp" <<'PY'
import sys, asyncio, pathlib
from atelier.config import cfg
from atelier import speech, images, audio, convert
from atelier.jobs import KINDS

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

d = pathlib.Path(sys.argv[1]); b = d / "bin"
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir()
cfg["tts"].update(bin=str(b / "piper"), voices_dir=str(d / "voices"))
cfg["images"].update(realesrgan_bin=str(b / "realesrgan"), rembg_bin=str(b / "rembg"))
cfg["audio"].update(demucs_bin=str(b / "demucs"), deepfilter_bin=str(b / "deepfilter"), demucs_device="cpu")
cfg["whisper"].update(bin=str(b / "whisper"), model=str(d / "whisper.bin"))

class Ctx:
    id = 99911
    deltas = []
    def set(self, *a, **k): pass
    def delta(self, t): self.deltas.append(t)

def go(kind, **p):
    c = Ctx(); c.deltas = []
    try:
        return asyncio.run(KINDS[kind].handler(c, p)), c
    except Exception as e:
        return e, c

check("jobs enregistrés", all(k in KINDS for k in ("tts", "dictate", "image", "audio")))
check("verrou GPU: upscale oui, rembg non", KINDS["image"].gpu({"action": "upscale"}) and not KINDS["image"].gpu({"action": "rembg"}))
check("verrou GPU: demucs cpu non", not KINDS["audio"].gpu({"action": "stems"}))

r, _ = go("tts", text="Bonjour le monde", lang="fr", mode="listen")
check("tts écoute -> wav dans .listen", isinstance(r, str) and r.endswith("99911.wav") and pathlib.Path(r).stat().st_size > 100)
r, _ = go("tts", text="Bonjour le monde", lang="fr", mode="mp3", title="Mon texte")
check("tts mp3", isinstance(r, str) and r.endswith(".mp3") and pathlib.Path(r).read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3") )
r, _ = go("tts", text="Hello", lang="de", mode="listen")
check("tts voix absente: commande de téléchargement", isinstance(r, Exception) and "download_voices" in str(r))
r, _ = go("tts", text="Hola", lang="pl", mode="listen")
check("tts langue sans voix: message config", isinstance(r, Exception) and "tts.voices" in str(r))
cfg["tts"]["bin"] = "piper-introuvable"
r, _ = go("tts", text="Bonjour", lang="fr")
check("tts sans piper: hint uv tool", isinstance(r, Exception) and "uv tool install piper-tts" in str(r))
cfg["tts"]["bin"] = str(b / "piper")

import shutil
shutil.copy(d / "song.wav", d / "data" / "mic.webm")
r, c = go("dictate", path=str(d / "data" / "mic.webm"), lang="fr")
check("dictée: texte nettoyé via delta", r is None and c.deltas == ["bonjour tout le monde"])

shutil.copy(d / "in.png", d / "a.png")
r, _ = go("image", path=str(d / "a.png"), action="upscale", factor=4, style="anime")
check("upscale x4 -> 256x192 png", isinstance(r, str) and r.endswith(".x4.png"))
import subprocess
w = subprocess.run(["vipsheader", "-f", "width", r], capture_output=True, text=True, env={"VIPS_WARNING": "0", "PATH": "/usr/bin"}).stdout.split()[-1] if isinstance(r, str) else "0"
check("x4 largeur 256", w == "256")
shutil.copy(d / "in.png", d / "a.png")
r, _ = go("image", path=str(d / "a.png"), action="upscale", factor=2)
w = subprocess.run(["vipsheader", "-f", "width", r], capture_output=True, text=True, env={"VIPS_WARNING": "0", "PATH": "/usr/bin"}).stdout.split()[-1] if isinstance(r, str) else "0"
check("x2 = x4 puis /2 (128)", w == "128")
(d / "data" / "uploads").mkdir(exist_ok=True)
up = d / "data" / "uploads" / "abcd1234-a.png"
shutil.copy(d / "in.png", up)
r, _ = go("image", path=str(up), action="rembg", model="u2net")
check("rembg -> .sans-fond.png, upload consommé", isinstance(r, str) and r.endswith("sans-fond.png") and not up.exists())
r, _ = go("image", path=str(d / "a.png"), action="rembg", model="evil; rm")
check("rembg modèle invalide refusé", isinstance(r, Exception))

shutil.copy(d / "song.wav", d / "s.wav")
r, _ = go("audio", path=str(d / "s.wav"), action="stems", model="htdemucs", format="mp3")
check("stems: dossier 4 pistes", isinstance(r, str) and sorted(p.name for p in pathlib.Path(r).iterdir()) == ["bass.mp3", "drums.mp3", "other.mp3", "vocals.mp3"])
shutil.copy(d / "song.wav", d / "s.wav")
r, _ = go("audio", path=str(d / "s.wav"), action="stems", model="htdemucs", format="mp3", two_stems=True)
check("stems 2 pistes", isinstance(r, str) and sorted(p.name for p in pathlib.Path(r).iterdir()) == ["no_vocals.mp3", "vocals.mp3"])
shutil.copy(d / "song.wav", d / "s.wav")
r, _ = go("audio", path=str(d / "s.wav"), action="denoise", format="flac")
check("denoise -> .denoised.flac", isinstance(r, str) and r.endswith(".denoised.flac") and pathlib.Path(r).stat().st_size > 100)
r, _ = go("audio", path=str(d / "s.wav"), action="stems", model="x", format="mp3")
check("source déjà consommée -> refusée", isinstance(r, Exception))
raise SystemExit(0 if ok else 1)
PY
t "plomberie hors-ligne" "[ $? = 0 ]"
for b in piper realesrgan-ncnn-vulkan rembg deep-filter; do command -v $b >/dev/null || echo "skip live $b: non installé"; done

# --- live (service redémarré requis)
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
new() { curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "{\"kind\":\"$1\",\"params\":{}}" $base/api/jobs; }
for k in tts dictate image audio; do t "service connaît '$k'" "[ \$(new $k) = 200 ]"; done
exit $fail
