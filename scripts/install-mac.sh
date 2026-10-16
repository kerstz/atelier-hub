#!/bin/bash
# Atelier installer for macOS (Apple Silicon + Intel, Homebrew). bash 3.2-safe. Called by install.sh on Darwin.
#   ./install.sh [--tier=minimal|standard|full] [--yes] [--dry-run] [--no-whisper] [--no-desktop]
#                [--no-service] [--ollama] [--models] [--engine=ct2]
# Tiers:  minimal  = core only (translate, YouTube, subtitles with existing captions)
#         standard = + OCR, documents, convert, whisper.cpp (Homebrew, Metal), LibreOffice, LanguageTool
#         full     = + e-books, TTS, background removal, upscaling, stems, denoise
# Ollama is always installed via Homebrew and started with `brew services` (--ollama is accepted, no-op).
# Not supported on macOS: live voice / Seed-VC, desktop GTK launcher.
set -uo pipefail
set -f  # package lists are word-split, never globbed (rembg[cpu,cli])
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIER=standard YES=0 DRY=0 WHISPER=1 SERVICE=1 MODELS=0 ENGINE=

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; }
for a in "$@"; do
  case $a in
    --tier=minimal|--tier=standard|--tier=full) TIER=${a#--tier=} ;;
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    --no-whisper) WHISPER=0 ;;
    --no-desktop|--ollama) ;;
    --no-service) SERVICE=0 ;;
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
confirm() { { [ "$YES" = 1 ] || [ "$DRY" = 1 ]; } && return 0; printf '%s [y/N] ' "$1"; read -r r; case $r in [yY]*) return 0 ;; esac; return 1; }

# ATELIER_FAKE_DARWIN=1 only prints the plan (dry-run) on another OS, for tests
FAKE=0
if [ "$(uname)" != Darwin ]; then
  if [ "${ATELIER_FAKE_DARWIN:-0}" = 1 ] && [ "$DRY" = 1 ]; then FAKE=1
  else echo "install-mac.sh: macOS only (use install.sh)" >&2; exit 1; fi
fi
ARCH=$(uname -m)

BREW=""
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && { BREW=$b; break; }; done
[ -z "$BREW" ] && have brew && BREW=$(command -v brew)
if [ -z "$BREW" ]; then
  if [ "$FAKE" = 1 ]; then BREW=brew
  else
    warn "Homebrew not found. Install it first: https://brew.sh then re-run ./install.sh"
    [ "$DRY" = 1 ] && BREW=brew || exit 1
  fi
fi
[ "$BREW" != brew ] && eval "$("$BREW" shellenv)"
export PATH="$HOME/.local/bin:$PATH"

formulae="ffmpeg yt-dlp poppler ollama"
have uv || formulae="uv $formulae"
casks=""
if [ "$TIER" != minimal ]; then
  formulae="$formulae pandoc tesseract tesseract-lang vips mpv languagetool ocrmypdf"
  [ "$WHISPER" = 1 ] && formulae="$formulae whisper-cpp"
  casks="libreoffice"
fi
[ "$TIER" = full ] && casks="$casks calibre"
uvtools=""
[ "$TIER" != minimal ] && uvtools="pdf2zh-next"
[ "$TIER" = full ] && uvtools="$uvtools piper-tts rembg[cpu,cli] demucs"

say "Atelier installer — macOS $ARCH, tier: $TIER$([ "$DRY" = 1 ] && echo ', dry-run')$([ "$FAKE" = 1 ] && echo ' (simulated)')"
echo "  repo: $ROOT"
echo "  brew formulae: $formulae"
[ -n "$casks" ] && echo "  brew casks: $casks"
[ -n "$uvtools" ] && echo "  python tools (uv tool): $uvtools"
[ "$TIER" != minimal ] && [ "$WHISPER" = 1 ] && echo "  whisper.cpp: Homebrew whisper-cpp + large-v3-turbo model (~1.6 GB) via scripts/build-whisper.sh"
[ "$TIER" = full ] && echo "  binaries: Real-ESRGAN ncnn-vulkan (macos zip) -> ~/.local/opt/realesrgan, deep-filter if an apple-darwin build exists"
echo "  Ollama: brew services start ollama"
[ "$MODELS" = 1 ] && echo "  Ollama models: the set recommended for this machine (python -m atelier.hw --models)"
[ "$ENGINE" = ct2 ] && echo "  CPU engine: ctranslate2 + sentencepiece, NLLB-200 int8 model from Hugging Face (CC-BY-NC, unverified repo id)"
[ "$SERVICE" = 1 ] && echo "  launchd agent: ~/Library/LaunchAgents/fr.atelier.plist (127.0.0.1:7777)"
echo "  not on macOS: live voice / Seed-VC, desktop GTK launcher (use the browser)"
confirm "Proceed?" || { echo "aborted."; exit 1; }

# ---- 1. Homebrew packages (bulk, then one by one)
say "Homebrew packages"
# shellcheck disable=SC2086
if ! run "$BREW" install $formulae; then
  warn "bulk install failed, retrying package by package"
  for p in $formulae; do run "$BREW" install "$p" || warn "not installed: $p"; done
fi
for c in $casks; do run "$BREW" install --cask "$c" || warn "not installed: --cask $c"; done

# ---- 2. python tools
if [ -n "$uvtools" ]; then
  say "Python tools"
  for t in $uvtools; do
    if [ "$t" = pdf2zh-next ]; then run uv tool install --python 3.12 "$t" || warn "failed: uv tool install $t"
    else run uv tool install "$t" || warn "failed: uv tool install $t"; fi
  done
fi

# ---- 3. binaries (Real-ESRGAN macos zip, deep-filter if published for darwin)
if [ "$TIER" = full ]; then
  say "Binaries (Real-ESRGAN, deep-filter)"
  rdir="$HOME/.local/opt/realesrgan"
  if [ ! -x "$rdir/realesrgan-ncnn-vulkan" ]; then
    run mkdir -p "$rdir" "$HOME/.local/bin"
    run curl -fL -o "$rdir/r.zip" "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"
    run unzip -oq "$rdir/r.zip" -d "$rdir"
    run chmod +x "$rdir/realesrgan-ncnn-vulkan"
    run xattr -dr com.apple.quarantine "$rdir"
  fi
  if [ ! -x "$HOME/.local/bin/deep-filter" ]; then
    case $ARCH in arm64) darch=aarch64 ;; *) darch=x86_64 ;; esac
    if [ "$DRY" = 1 ]; then
      echo "  (dry-run) query api.github.com/repos/Rikorose/DeepFilterNet/releases/latest for a deep-filter-*-$darch-apple-darwin asset"
    else
      url=$(curl -fsSL https://api.github.com/repos/Rikorose/DeepFilterNet/releases/latest 2>/dev/null \
        | grep -o '"browser_download_url": *"[^"]*deep-filter-[^"]*'"$darch"'-apple-darwin[^"]*"' | head -1 | sed 's/.*"\(http[^"]*\)"$/\1/')
      if [ -n "$url" ]; then
        run curl -fL -o "$HOME/.local/bin/deep-filter" "$url" && run chmod +x "$HOME/.local/bin/deep-filter"
      else
        echo "  note: no $darch-apple-darwin deep-filter build published: denoise skipped"
      fi
    fi
  fi
fi

# ---- 4. whisper model (whisper-cli comes from Homebrew)
if [ "$TIER" != minimal ] && [ "$WHISPER" = 1 ]; then
  say "whisper.cpp model"
  run /bin/bash "$ROOT/scripts/build-whisper.sh" || warn "whisper setup failed: run scripts/build-whisper.sh again"
fi

# ---- 5. Ollama
say "Ollama"
run "$BREW" services start ollama || warn "could not start ollama (brew services list)"

# ---- 6. Atelier itself
say "Atelier"
cd "$ROOT" || exit 1
run uv sync --frozen
[ "$SERVICE" = 1 ] && run /bin/bash scripts/install-service.sh

if [ "$MODELS" = 1 ] || [ "$ENGINE" = ct2 ]; then
  say "Hardware profile"
  [ "$DRY" = 1 ] && echo '  $ uv run --frozen python -m atelier.hw' || uv run --frozen python -m atelier.hw
fi
if [ "$MODELS" = 1 ]; then
  say "Ollama models (recommended for this machine)"
  if [ "$DRY" = 1 ]; then echo '  $ ollama pull <models from: python -m atelier.hw --models>'
  else
    models=$(uv run --frozen python -m atelier.hw --models 2>/dev/null)
    [ -z "$models" ] && models="translategemma:12b gemma3:12b"
    for m in $models; do run ollama pull "$m" || warn "ollama pull $m failed (is ollama running? brew services list)"; done
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
    uv run --no-sync python -c "from huggingface_hub import snapshot_download; snapshot_download('JustFrederik/${nllb}-ct2-int8', local_dir='$mdir')" \
      || warn "download failed: put a CTranslate2 NLLB model (model.bin + sentencepiece .model) in $mdir"
  fi
fi

say "Check"
[ "$DRY" = 1 ] && echo "  (dry-run) would run: bash scripts/env-check.sh" || /bin/bash scripts/env-check.sh || true
echo
echo "Done. Open http://127.0.0.1:7777 — the System tab lists anything still missing, with the command to fix it."
[ "$MODELS" = 1 ] || echo "Models: ollama pull translategemma:12b && ollama pull gemma3:12b   (or re-run with --models)"
echo "Note: live voice (Seed-VC) and the desktop GTK launcher are not supported on macOS."
