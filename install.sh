#!/usr/bin/env bash
# Atelier installer: detects the distro and installs what the chosen tier needs.
#   ./install.sh [--tier=minimal|standard|full] [--yes] [--dry-run] [--no-whisper] [--no-desktop]
#                [--no-service] [--ollama] [--models] [--engine=ct2]
# Tiers:  minimal  = core only (translate, YouTube, subtitles with existing captions)
#         standard = + OCR, documents, convert, whisper.cpp, desktop entry   (default)
#         full     = + e-books, TTS, background removal, upscaling, stems, denoise
# --models  pulls the Ollama models recommended for THIS machine (VRAM/RAM based; see: python -m atelier.hw)
# --engine=ct2  CPU translation engine for small machines: NLLB-200 via CTranslate2 (no GPU/LLM needed)
# Nothing is downloaded or built without being listed first (use --dry-run to only print the plan).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
TIER=standard YES=0 DRY=0 WHISPER=1 DESKTOP=1 SERVICE=1 OLLAMA=0 MODELS=0 ENGINE=

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }
for a in "$@"; do
  case $a in
    --tier=minimal|--tier=standard|--tier=full) TIER=${a#--tier=} ;;
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    --no-whisper) WHISPER=0 ;;
    --no-desktop) DESKTOP=0 ;;
    --no-service) SERVICE=0 ;;
    --ollama) OLLAMA=1 ;;
    --models|--models=auto) MODELS=1 ;;
    --engine=ct2) ENGINE=ct2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $a" >&2; usage >&2; exit 64 ;;
  esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*" >&2; }
run() { printf '  $ %s\n' "$*"; [ "$DRY" = 1 ] || "$@"; }
have() { command -v "$1" >/dev/null 2>&1; }
confirm() { [ "$YES" = 1 ] || [ "$DRY" = 1 ] && return 0; read -r -p "$1 [y/N] " r; [[ $r == [yY]* ]]; }

# ---- distro detection (ATELIER_OS_RELEASE lets tests simulate another distro)
OSREL="${ATELIER_OS_RELEASE:-/etc/os-release}"
distro_id="" distro_like=""
if [ -r "$OSREL" ]; then
  distro_id=$(. "$OSREL"; echo "${ID:-}")
  distro_like=$(. "$OSREL"; echo "${ID_LIKE:-}")
fi
family=unknown
for w in $distro_id $distro_like; do
  case $w in
    arch|cachyos|manjaro|endeavouros|garuda|artix|arcolinux) family=arch; break ;;
    debian|ubuntu|linuxmint|pop|raspbian|zorin|elementary|neon|kali) family=debian; break ;;
    fedora|rhel|centos|rocky|almalinux|nobara|bazzite|ultramarine) family=fedora; break ;;
    opensuse*|suse|sles|sled) family=suse; break ;;
  esac
done

# ---- package names per family and group
declare -A PM_INSTALL=(
  [arch]="pacman -S --needed --noconfirm" [debian]="apt-get install -y"
  [fedora]="dnf install -y" [suse]="zypper --non-interactive install"
)
declare -A CORE=(
  [arch]="git curl unzip ffmpeg poppler xdg-utils"
  [debian]="git curl unzip ffmpeg poppler-utils xdg-utils"
  [fedora]="git curl unzip ffmpeg-free poppler-utils xdg-utils"
  [suse]="git curl unzip ffmpeg poppler-tools xdg-utils"
)
declare -A STANDARD=(
  [arch]="tesseract tesseract-data-eng tesseract-data-fra pandoc-cli libreoffice-fresh libvips libnotify wl-clipboard"
  [debian]="tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra pandoc libreoffice libvips-tools libnotify-bin wl-clipboard"
  [fedora]="tesseract tesseract-langpack-eng tesseract-langpack-fra pandoc libreoffice vips-tools libnotify wl-clipboard"
  [suse]="tesseract-ocr tesseract-ocr-traineddata-english tesseract-ocr-traineddata-french pandoc libreoffice vips-tools libnotify-tools wl-clipboard"
)
declare -A BUILD=(  # whisper.cpp with Vulkan
  [arch]="cmake base-devel vulkan-headers vulkan-icd-loader shaderc"
  [debian]="cmake build-essential libvulkan-dev glslc"
  [fedora]="cmake gcc-c++ vulkan-headers vulkan-loader-devel glslc"
  [suse]="cmake gcc-c++ vulkan-devel shaderc"
)
declare -A DESKTOP_PKGS=(  # native window: PyGObject + WebKitGTK (system python)
  [arch]="python-gobject webkit2gtk-4.1 gtk3"
  [debian]="python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
  [fedora]="python3-gobject gtk3 webkit2gtk4.1"
  [suse]="python3-gobject typelib-1_0-Gtk-3_0 typelib-1_0-WebKit2-4_1"
)
declare -A FULL=(
  [arch]="calibre"
  [debian]="calibre"
  [fedora]="calibre"
  [suse]="calibre"
)

if [ "$family" = unknown ]; then
  warn "Unrecognized distro (ID=$distro_id ID_LIKE=$distro_like): system packages are NOT installed."
  warn "Install by hand: git curl unzip ffmpeg poppler(pdftotext), and for the standard tier tesseract (+fra,eng),"
  warn "pandoc, LibreOffice, libvips, libnotify, wl-clipboard. Python tools and Atelier itself are still set up below."
fi

sudo_cmd=""
if [ "$(id -u)" != 0 ]; then
  if have sudo; then sudo_cmd="sudo"; elif [ "$family" != unknown ] && [ "$DRY" = 0 ]; then
    warn "sudo not found and you are not root: cannot install system packages."; exit 1
  fi
fi

pkgs=()
add() { read -ra _p <<< "${1:-}"; pkgs+=("${_p[@]}"); }
if [ "$family" != unknown ]; then
  add "${CORE[$family]}"
  if [ "$TIER" != minimal ]; then
    add "${STANDARD[$family]}"
    [ "$WHISPER" = 1 ] && add "${BUILD[$family]}"
    [ "$DESKTOP" = 1 ] && add "${DESKTOP_PKGS[$family]}"
  fi
  [ "$TIER" = full ] && add "${FULL[$family]}"
  if [ "$OLLAMA" = 1 ] && [ "$family" = arch ]; then
    if have lspci && lspci 2>/dev/null | grep -qi nvidia; then add ollama-cuda; else add ollama-vulkan; fi
  fi
fi

say "Atelier installer — distro: ${distro_id:-?} (family: $family), tier: $TIER$([ "$DRY" = 1 ] && echo ', dry-run')"
echo "  repo: $ROOT"
[ ${#pkgs[@]} -gt 0 ] && echo "  system packages (${PM_INSTALL[$family]%% *}): ${pkgs[*]}"
echo "  python tools (uv tool): yt-dlp$([ "$TIER" != minimal ] && echo ' pdf2zh-next ocrmypdf')$([ "$TIER" = full ] && echo ' piper-tts rembg demucs')"
[ "$TIER" != minimal ] && [ "$WHISPER" = 1 ] && echo "  whisper.cpp: clone + Vulkan build + large-v3-turbo model (~1.6 GB) via scripts/build-whisper.sh"
[ "$TIER" = full ] && echo "  binaries (x86_64): Real-ESRGAN ncnn-vulkan -> ~/.local/opt/realesrgan, deep-filter -> ~/.local/bin"
[ "$OLLAMA" = 1 ] && echo "  Ollama: $([ "$family" = arch ] && echo 'distro package' || echo 'official installer https://ollama.com/install.sh')"
[ "$MODELS" = 1 ] && echo "  Ollama models: the set recommended for this machine (python -m atelier.hw --models)"
[ "$ENGINE" = ct2 ] && echo "  CPU engine: ctranslate2 + sentencepiece, NLLB-200 int8 model from Hugging Face (CC-BY-NC, unverified repo id)"
[ "$SERVICE" = 1 ] && echo "  systemd --user unit: atelier.service (127.0.0.1:7777)"
[ "$DESKTOP" = 1 ] && [ "$TIER" != minimal ] && echo "  desktop: menu entry + native window"
confirm "Proceed?" || { echo "aborted."; exit 1; }

# ---- 1. system packages (bulk first, then one by one so a missing package does not block the rest)
if [ ${#pkgs[@]} -gt 0 ]; then
  say "System packages"
  [ "$family" = debian ] && run $sudo_cmd apt-get update
  # shellcheck disable=SC2086
  if ! run $sudo_cmd ${PM_INSTALL[$family]} "${pkgs[@]}"; then
    warn "bulk install failed, retrying package by package"
    for p in "${pkgs[@]}"; do
      # shellcheck disable=SC2086
      run $sudo_cmd ${PM_INSTALL[$family]} "$p" || warn "not installed: $p (skip or install it by hand)"
    done
  fi
fi

# ---- 2. uv
if ! have uv; then
  say "uv"
  if [ "$family" = arch ]; then
    run $sudo_cmd pacman -S --needed --noconfirm uv
  else
    echo "  uv is not packaged everywhere; official installer: https://astral.sh/uv/install.sh"
    if confirm "Run the official uv installer?"; then
      [ "$DRY" = 1 ] && echo '  $ curl -LsSf https://astral.sh/uv/install.sh | sh' || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
      export PATH="$HOME/.local/bin:$PATH"
    else
      warn "uv is required: https://docs.astral.sh/uv/getting-started/installation/"; exit 1
    fi
  fi
fi
export PATH="$HOME/.local/bin:$PATH"

# ---- 3. python tools
say "Python tools"
tool() { run uv tool install "$@" || warn "failed: uv tool install $*"; }
tool yt-dlp
if [ "$TIER" != minimal ]; then
  tool --python 3.12 pdf2zh-next
  tool ocrmypdf
fi
if [ "$TIER" = full ]; then
  tool piper-tts
  tool "rembg[cpu,cli]"
  tool demucs
fi

# ---- 4. binaries without a distro package (x86_64 only)
if [ "$TIER" = full ]; then
  say "Binaries (Real-ESRGAN, deep-filter)"
  if [ "$(uname -m)" = x86_64 ]; then
    if [ ! -x "$HOME/.local/opt/realesrgan/realesrgan-ncnn-vulkan" ]; then
      run mkdir -p "$HOME/.local/opt/realesrgan" "$HOME/.local/bin"
      run curl -fL -o "$HOME/.local/opt/realesrgan/r.zip" "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip"
      run unzip -oq "$HOME/.local/opt/realesrgan/r.zip" -d "$HOME/.local/opt/realesrgan"
      run chmod +x "$HOME/.local/opt/realesrgan/realesrgan-ncnn-vulkan"
    fi
    if [ ! -x "$HOME/.local/bin/deep-filter" ]; then
      run curl -fL -o "$HOME/.local/bin/deep-filter" "https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl"
      run chmod +x "$HOME/.local/bin/deep-filter"
    fi
  else
    warn "non-x86_64: get Real-ESRGAN ncnn-vulkan and deep-filter from their GitHub releases by hand."
  fi
fi

# ---- 5. whisper.cpp
if [ "$TIER" != minimal ] && [ "$WHISPER" = 1 ]; then
  say "whisper.cpp (Vulkan build, several minutes)"
  run bash "$ROOT/scripts/build-whisper.sh" || warn "whisper.cpp build failed: run scripts/build-whisper.sh again after fixing the error"
fi

# ---- 6. Ollama
if [ "$OLLAMA" = 1 ]; then
  say "Ollama"
  if have ollama; then echo "  already installed"
  elif [ "$family" = arch ]; then
    run $sudo_cmd systemctl enable --now ollama || warn "could not start ollama.service"
  else
    echo "  official installer: https://ollama.com/install.sh"
    if confirm "Run the official Ollama installer?"; then
      [ "$DRY" = 1 ] && echo '  $ curl -fsSL https://ollama.com/install.sh | sh' || { curl -fsSL https://ollama.com/install.sh | sh; }
    fi
  fi
fi

# ---- 7. Atelier itself
say "Atelier"
cd "$ROOT" || exit 1
run uv sync --frozen
[ "$SERVICE" = 1 ] && run bash scripts/install-service.sh
[ "$DESKTOP" = 1 ] && [ "$TIER" != minimal ] && run bash scripts/install-desktop.sh

if [ "$MODELS" = 1 ] || [ "$ENGINE" = ct2 ]; then
  say "Hardware profile"
  [ "$DRY" = 1 ] && echo '  $ uv run --frozen python -m atelier.hw' || uv run --frozen python -m atelier.hw
fi
if [ "$MODELS" = 1 ]; then
  say "Ollama models (recommended for this machine)"
  if [ "$DRY" = 1 ]; then echo '  $ ollama pull <models from: python -m atelier.hw --models>'
  else
    mapfile -t _models < <(uv run --frozen python -m atelier.hw --models 2>/dev/null)
    [ ${#_models[@]} -eq 0 ] && _models=(translategemma:12b gemma3:12b)
    for m in "${_models[@]}"; do run ollama pull "$m" || warn "ollama pull $m failed (is the ollama service running?)"; done
  fi
fi
if [ "$ENGINE" = ct2 ]; then
  say "CPU translation engine (NLLB-200, CTranslate2)"
  mdir="$HOME/.local/share/atelier/nllb-200-distilled-600M-int8"
  run uv pip install --python "$ROOT/.venv/bin/python" ctranslate2 sentencepiece huggingface_hub
  if [ "$DRY" = 1 ]; then
    echo "  \$ huggingface_hub.snapshot_download('JustFrederik/<nllb model>-ct2-int8', local_dir='$mdir')"
  elif confirm "Download the NLLB model (600M ~0.6 GB, 1.3B ~1.4 GB, license CC-BY-NC)?"; then
    nllb=$(uv run --frozen python -m atelier.hw --ct2 2>/dev/null); nllb=${nllb:-nllb-200-distilled-600M}
    # the config points at the 600M directory: a bigger model is stored there too (single model_dir)
    uv run --no-sync python -c "from huggingface_hub import snapshot_download; snapshot_download('JustFrederik/${nllb}-ct2-int8', local_dir='$mdir')" \
      || warn "download failed: put a CTranslate2 NLLB model (model.bin + sentencepiece .model) in $mdir"
  fi
fi

say "Check"
[ "$DRY" = 1 ] && echo "  (dry-run) would run: bash scripts/env-check.sh" || bash scripts/env-check.sh || true
cat <<MSG

Done. Open http://127.0.0.1:7777 — the System tab lists anything still missing, with the command to fix it.
$([ "$MODELS" = 1 ] || echo "Models: ollama pull translategemma:12b && ollama pull gemma3:12b   (or re-run with --models)")
MSG
