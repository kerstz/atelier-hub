#!/usr/bin/env bash
# Installe Seed-VC (changeur de voix IA, GPL-3.0) pour l'onglet Audio > Voix. À lancer par l'utilisateur.
# Télécharge ~3-4 Go de poids au préchauffage. Options: --dry-run, --torch-index URL, --no-warmup
set -euo pipefail
dry=0; warm=1
idx="https://download.pytorch.org/whl/rocm6.1"
SEED="${ATELIER_SEEDVC_DIR:-$HOME/.local/opt/seed-vc}"
VENV="${ATELIER_SEEDVC_VENV:-$HOME/.local/share/atelier/seedvc-venv}"
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) dry=1;;
    --no-warmup) warm=0;;
    --torch-index) idx=$2; shift;;
    -h|--help) sed -n 2,4p "$0"; exit 0;;
    *) echo "option inconnue: $1" >&2; exit 64;;
  esac; shift
done
run() { echo "+ $*"; [ $dry = 1 ] || "$@"; }
command -v uv >/dev/null || { echo "uv introuvable" >&2; exit 1; }
command -v git >/dev/null || { echo "git introuvable" >&2; exit 1; }
for b in parec pacat pw-loopback; do command -v $b >/dev/null || echo "avertissement: $b absent (direct impossible)" >&2; done

[ -d "$SEED/.git" ] || run git clone --depth 1 https://github.com/Plachtaa/seed-vc "$SEED"
[ -x "$VENV/bin/python" ] || run uv venv --python 3.10 "$VENV"
run uv pip install --reinstall-package torch --reinstall-package torchaudio --python "$VENV/bin/python" torch==2.4.0 torchaudio==2.4.0 --index-url "$idx"
if [ $dry = 0 ]; then
  "$VENV/bin/python" -c "import torch,sys; print('torch', torch.__version__, 'hip', torch.version.hip); sys.exit(0 if torch.version.hip else 1)" \
    || { echo "torch n'est pas un build ROCm (cu121 = CUDA, inutile sur AMD). Vérifier --torch-index." >&2; exit 1; }
fi
run uv pip install --python "$VENV/bin/python" scipy==1.13.1 librosa==0.10.2 "huggingface-hub>=0.28.1" munch==4.0.0 einops==0.8.0 \
  descript-audio-codec==1.0.0 pydub==0.25.1 transformers==4.46.3 soundfile==0.12.1 numpy==1.26.4 hydra-core==1.3.2 \
  pyyaml python-dotenv tqdm accelerate sounddevice==0.5.0
run uv pip install --python "$VENV/bin/python" demucs  # séparation voix/musique sur le même torch ROCm

if [ $warm = 1 ]; then
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  echo "préchauffage (télécharge les poids)…"
  if [ $dry = 1 ]; then echo "+ (inference.py puis real-time-gui load_models)"; exit 0; fi
  ffmpeg -loglevel error -f lavfi -i "sine=f=220:d=3" -ar 22050 -ac 1 "$t/a.wav"
  ffmpeg -loglevel error -f lavfi -i "sine=f=330:d=3" -ar 22050 -ac 1 "$t/b.wav"
  (cd "$SEED" && "$VENV/bin/python" inference.py --source "$t/a.wav" --target "$t/b.wav" --output "$t/o" --diffusion-steps 4)
  (cd "$SEED" && "$VENV/bin/python" - <<'PY'
import sys, types, importlib.util, torch
sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("rtg", "real-time-gui.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("device:", m.device)
m.load_models(types.SimpleNamespace(fp16=True, checkpoint_path=None, config_path=None, gpu=0))
print("modèle direct chargé")
PY
  )
fi
if [ "$(uname)" = Darwin ]; then rs="launchctl kickstart -k gui/$(id -u)/fr.atelier"; else rs="systemctl --user restart atelier"; fi
echo "ok. Ensuite: scripts/voice-refs.sh --piper  puis  $rs"
