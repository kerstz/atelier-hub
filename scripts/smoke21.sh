#!/usr/bin/env bash
# Phase 21 — Voix: tout hors-ligne (faux Seed-VC, faux demucs, faux pw-loopback/ffmpeg/parec); aucun modèle.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/fake" "$tmp/seed/bin" "$tmp/voices" "$tmp/data"

t "voice.js: syntaxe" "node --check static/voice.js"
t "worker: syntaxe + SPDX GPL" "python3 -m py_compile atelier/voicelive_worker.py && head -1 atelier/voicelive_worker.py | grep -q GPL-3.0"
t "voice-setup.sh: syntaxe + dry-run (venv, torch ROCm, poids)" "bash -n scripts/voice-setup.sh && scripts/voice-setup.sh --dry-run --no-warmup | grep -q rocm"
t "voice-refs.sh: 15 voix (10 FR + 5 EN) en dry-run" "[ \$(scripts/voice-refs.sh --dry-run | grep -c ' <- ') = 15 ]"
t "résultats dans l'app: Voir/Aperçu/Écouter + /api/jobs/{id}/view" "grep -q '/view' static/app.js && grep -q 'preview' static/ui.js && grep -q 'job_view' atelier/main.py"
t "UI: carte voix montée dans l'onglet Audio" "grep -q 'id=\"vc-root\"' static/index.html && grep -q 'voice.js' static/index.html"

# faux Seed-VC: python = bash. inference.py et voicelive_worker.py sont "interprétés" ici.
cat > "$tmp/seed/bin/python" <<'S'
#!/usr/bin/env bash
script=$1; shift
case $script in
  *inference.py)
    echo "inference $*" >> "$FAKE_LOG"
    while [ $# -gt 0 ]; do case $1 in --output) o=$2; shift;; esac; shift; done
    mkdir -p "$o"; ffmpeg -loglevel error -f lavfi -i sine=f=500:d=2 -ar 22050 -y "$o/vc_x.wav";;
  *voicelive_worker.py)
    echo "worker $*" >> "$FAKE_LOG"
    echo '{"ready": true, "sr": 22050, "latency_ms": 300}'
    n=0
    while read -r line; do echo "ctl $line" >> "$FAKE_LOG"; n=$((n+1)); echo "{\"in_db\": -30.0, \"out_db\": -28.0, \"infer_ms\": 42, \"overruns\": $n, \"speech\": true}"; done;;
esac
S
cat > "$tmp/fake/demucs" <<'S'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case $1 in -n) n=$2; shift;; -o) o=$2; shift;; -d) shift;; --two-stems) shift;; *) f=$1;; esac; shift; done
d="$o/$n/$(basename "$f" .wav)"; mkdir -p "$d"
ffmpeg -loglevel error -f lavfi -i sine=f=200:d=2 -y "$d/vocals.wav"
ffmpeg -loglevel error -f lavfi -i sine=f=100:d=2 -y "$d/no_vocals.wav"
S
cat > "$tmp/fake/pw-loopback" <<'S'
#!/usr/bin/env bash
echo "loopback $*" >> "$FAKE_LOG"; exec -a fake-pw-loopback sleep 300
S
cat > "$tmp/fake/parec" <<'S'
#!/usr/bin/env bash
exec sleep 300
S
chmod +x "$tmp/seed/bin/python" "$tmp/fake/"*
: > "$tmp/seed/inference.py"; : > "$tmp/seed/real-time-gui.py"
ffmpeg -loglevel error -f lavfi -i sine=f=300:d=2 -y "$tmp/song.wav"
ffmpeg -loglevel error -f lavfi -i sine=f=250:d=5 -y "$tmp/ref5.wav"
ffmpeg -loglevel error -f lavfi -i testsrc=s=64x48:d=2 -f lavfi -i sine=f=300:d=2 -shortest -y "$tmp/clip.mp4"
HAS_RB=0; ffmpeg -hide_banner -filters 2>/dev/null | grep -q rubberband && HAS_RB=1

export FAKE_LOG="$tmp/log"; : > "$FAKE_LOG"
py - "$tmp" "$HAS_RB" <<'PY'
import sys, os, asyncio, pathlib, subprocess, json, shutil, time
from atelier.config import cfg
from atelier import voice, voicelive, audio
from atelier.jobs import KINDS
from atelier.voicedsp import FX, chain

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

d = pathlib.Path(sys.argv[1]); has_rb = sys.argv[2] == "1"
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
cfg["voice"].update(python=str(d / "seed/bin/python"), seedvc_dir=str(d / "seed"), voices_dir=str(d / "voices"))
cfg["audio"].update(demucs_bin=str(d / "fake/demucs"), demucs_device="cpu")
log = lambda: pathlib.Path(os.environ["FAKE_LOG"]).read_text()

class Ctx:
    id = 99921
    def set(self, *a, **k): pass
    def delta(self, t): pass

def go(kind, **p):
    try:
        return asyncio.run(KINDS[kind].handler(Ctx(), p))
    except Exception as e:
        return e

def dur(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout or 0)

def streams(f):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.split()

cat = voice.catalogue()
check("catalogue: 10 voix FR + 5 EN + effets", sum(v.get("lang") == "fr" for v in cat if v["kind"] == "ai" and not v["custom"]) == 10 and
      sum(v.get("lang") == "en" for v in cat if v["kind"] == "ai") == 5 and sum(v["kind"] == "fx" for v in cat) == len(FX) >= 7)
check("jobs voice + voice_live; live prend le GPU seulement avec seedvc",
      "voice" in KINDS and KINDS["voice_live"].gpu({"_gpu": True}) and not KINDS["voice_live"].gpu({"_gpu": False}))
# Seed-VC absent
shutil.move(d / "seed", d / "seed.off")
ds = {v["id"]: v for v in voice.describe()}
check("sans Seed-VC: voix IA non prêtes, effets prêts", not ds["homme-pose"]["ready"] and ds["fx-robot"]["ready"])
shutil.copy(d / "song.wav", d / "s.wav")
r = go("voice", path=str(d / "s.wav"), voice="homme-pose", format="wav", separate=False)
check("voix IA sans Seed-VC: message d'installation", isinstance(r, Exception) and "voice-setup.sh" in str(r))
shutil.move(d / "seed.off", d / "seed")
r = go("voice", path=str(d / "s.wav"), voice="homme-pose", format="wav", separate=False)
check("voix IA sans référence: message voice-refs", isinstance(r, Exception) and "voice-refs.sh" in str(r))

# effet DSP (vrai ffmpeg)
fx = "fx-helium" if has_rb else "fx-robot"
r = go("voice", path=str(d / "s.wav"), voice=fx, format="wav", separate=False)
check(f"fichier effet {fx}: wav de même durée", isinstance(r, str) and r.endswith(f".voix-{fx}.wav") and abs(dur(r) - 2) < 0.3)
check("source consommée par le gestionnaire (pas par le handler)", (d / "s.wav").exists())
r = go("voice", path=str(d / "s.wav"), voice="fx-radio", format="mp3", separate=True, keep_music=True)
check("effet + séparation + musique gardée -> mp3", isinstance(r, str) and r.endswith(".mp3") and dur(r) > 1.5)
r = go("voice", path=str(d / "s.wav"), voice="fx-cave", format="ogg")
check("format invalide refusé", isinstance(r, Exception))
r = go("voice", path=str(d / "s.wav"), voice="inconnue", format="wav")
check("voix inconnue refusée", isinstance(r, Exception))

# voix IA avec faux Seed-VC
for vid in ("homme-pose", "voix-agee"):
    shutil.copy(d / "song.wav", d / "voices" / f"{vid}.wav")
open(os.environ["FAKE_LOG"], "w").close()
r = go("voice", path=str(d / "s.wav"), voice="homme-pose", format="flac", separate=True, keep_music=False)
L = log()
check("IA: inference.py reçoit la référence, 30 étapes, voix séparée",
      isinstance(r, str) and r.endswith(".flac") and f"--target {d}/voices/homme-pose.wav" in L and "--diffusion-steps 30" in L and "vocals.wav" in L)
r = go("voice", path=str(d / "s.wav"), voice="voix-agee", format="wav", separate=False)
check("IA + post-traitement âgé (tremolo) appliqué", isinstance(r, str) and "tremolo" in chain("age") and abs(dur(r) - 2) < 0.3)
r = go("voice", path=str(d / "clip.mp4"), voice="homme-pose", format="mkv", separate=False)
check("source vidéo -> mkv: flux vidéo copié + audio remplacé", isinstance(r, str) and sorted(streams(r)) == ["audio", "video"])
cfg["voice"]["engine"] = "dsp"
r = go("voice", path=str(d / "s.wav"), voice="homme-pose", format="wav", separate=False)
check("engine=dsp: voix IA refusée avec explication", isinstance(r, Exception) and "seedvc" in str(r))
cfg["voice"]["engine"] = "auto"

# ajout d'une voix perso
from fastapi import HTTPException
up = d / "data" / "uploads"; up.mkdir(parents=True, exist_ok=True)
shutil.copy(d / "ref5.wav", up / "aa-ref.wav")
try:
    asyncio.run(voice.add_voice(voice.AddIn(path=str(up / "aa-ref.wav"), name="Ma voix", rights=False))); e1 = None
except HTTPException as e:
    e1 = e.status_code
check("voix perso sans case de droits -> 400", e1 == 400)
r = asyncio.run(voice.add_voice(voice.AddIn(path=str(up / "aa-ref.wav"), name="Ma voix", rights=True)))
check("voix perso ajoutée (c-ma-voix) et listée", r["id"] == "c-ma-voix" and any(v["id"] == "c-ma-voix" for v in voice.catalogue()))
asyncio.run(voice.delete_voice("c-ma-voix"))
check("voix perso supprimée", not any(v["id"] == "c-ma-voix" for v in voice.catalogue()))
try:
    asyncio.run(voice.delete_voice("femme-claire")); e2 = None
except HTTPException as e:
    e2 = e.status_code
check("voix du catalogue non supprimable", e2 == 400)

# filigrane (image)
from atelier import images
subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1", "-frames:v", "1", "-y", str(d / "w.png")])
r = go("image", path=str(d / "w.png"), action="watermark", zone="br")
print("DEBUG filigrane:", repr(r), file=sys.stderr)
check("filigrane coin bas-droite -> .sans-filigrane.png, même taille", isinstance(r, str) and r.endswith(".sans-filigrane.png") and
      subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", r], capture_output=True, text=True).stdout.strip() == "320,240")
r = go("image", path=str(d / "w.png"), action="watermark", zone="x")
check("filigrane zone inconnue refusée", isinstance(r, Exception))
r = go("image", path=str(d / "w.png"), action="watermark", zone="c", w_pct="abc")
check("filigrane paramètre invalide refusé", isinstance(r, Exception))

# direct
os.environ["PATH"] = f"{d}/fake:" + os.environ["PATH"]
cat_ = pathlib.Path(d / "fake" / "ffmpeg")
cat_.write_text('#!/usr/bin/env bash\necho "ffmpeg $*" >> "$FAKE_LOG"; exec -a fake-ffmpeg sleep 300\n'); cat_.chmod(0o755)
real_ffmpeg = shutil.which("ffmpeg", path="/usr/bin")

def pg(pat):
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0

async def live_dsp():
    t = asyncio.create_task(voicelive.live(Ctx(), {"voice": "fx-robot", "source": "mic0"}))
    await asyncio.sleep(1.0)
    st = dict(voicelive.STATE)
    voicelive._ctl.put_nowait({"voice": "fx-demon"})
    await asyncio.sleep(1.0)
    st2 = dict(voicelive.STATE)
    voicelive._ctl.put_nowait({"op": "stop"})
    await asyncio.wait_for(t, 5)
    return st, st2

open(os.environ["FAKE_LOG"], "w").close()
st, st2 = asyncio.run(live_dsp())
L = log()
check("direct DSP: micro virtuel créé + ffmpeg pulse -> atelier_vc_sink avec la chaîne",
      st["running"] and st["engine"] == "dsp" and "loopback" in L and "atelier_vc_mic" in L and "-i mic0" in L and "atelier_vc_sink" in L and "aeval" in L)
check("direct DSP: changement de voix à chaud relance ffmpeg avec la nouvelle chaîne",
      st2["voice"] == "fx-demon" and L.count("ffmpeg ") == 2 and "rubberband=pitch=0.62" in L)
time.sleep(0.3)
check("direct: arrêt tue loopback + ffmpeg, état libéré", not pg("^fake-pw-loopback 300$") and not pg("^fake-ffmpeg 300$") and not voicelive.STATE.get("running"))

async def live_ai():
    t = asyncio.create_task(voicelive.live(Ctx(), {"voice": "homme-pose"}))
    await asyncio.sleep(1.2)
    st = dict(voicelive.STATE)
    voicelive._ctl.put_nowait({"bypass": True})
    voicelive._ctl.put_nowait({"voice": "voix-agee"})
    await asyncio.sleep(1.0)
    st2 = dict(voicelive.STATE)
    voicelive._ctl.put_nowait({"op": "stop"})
    await asyncio.wait_for(t, 5)
    return st, st2

open(os.environ["FAKE_LOG"], "w").close()
st, st2 = asyncio.run(live_ai())
L = log()
check("direct IA: worker lancé avec source par défaut, sink, bloc et étapes",
      st["engine"] == "seedvc" and "worker " in L and "--sink atelier_vc_sink" in L and "--block 0.18" in L and "--steps 6" in L and "--source  --sink" in L)  # default source = "" (worker picks the default)
check("direct IA: prêt + statistiques du worker remontées", st["ready"] and st2["stats"].get("infer_ms") == 42)
check("direct IA: bypass et changement de voix transmis au worker (JSON stdin)",
      '"bypass": true' in L and 'voices/voix-agee.wav' in L and st2["voice"] == "voix-agee")
time.sleep(0.3)
check("direct IA: arrêt tue loopback + worker", not pg("^fake-pw-loopback 300$") and not pg("seed/bin/python"))

cfg["voice"]["live_max_minutes"] = 0.03
async def live_max():
    t = asyncio.create_task(voicelive.live(Ctx(), {"voice": "fx-cave"}))
    await asyncio.wait_for(t, 6)
asyncio.run(live_max())
check("direct: arrêt automatique à la durée maximale", not voicelive.STATE.get("running"))
cfg["voice"]["live_max_minutes"] = 120

async def live_crash():
    t = asyncio.create_task(voicelive.live(Ctx(), {"voice": "fx-cave"}))
    await asyncio.sleep(0.8)
    subprocess.run(["pkill", "-f", "^fake-ffmpeg 300$"])
    try:
        await asyncio.wait_for(t, 5)
        return None
    except RuntimeError as e:
        return str(e)
msg = asyncio.run(live_crash())
check("direct: moteur mort -> la tâche échoue, rien ne traîne", msg and "moteur voix" in msg and not pg("^fake-pw-loopback 300$"))

sys.exit(0 if ok else 1)
PY
[ $? = 0 ] || fail=1
[ $fail = 0 ] && echo "smoke21 ok" || { echo "smoke21 ECHEC"; exit 1; }
