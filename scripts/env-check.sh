#!/usr/bin/env bash
ok() { printf '  ok      %s\n' "$1"; }
ko() { printf '  MANQUE  %s\n' "$1"; }
chk() { if command -v "$1" >/dev/null 2>&1; then ok "$1 ($(command -v "$1"))"; else ko "$1 -> $2"; fi; }

if [ "$(uname)" = Darwin ]; then
  echo "[outils]"
  chk brew "https://brew.sh"
  chk uv "brew install uv"
  for t in yt-dlp ffmpeg pdftotext pandoc tesseract vips mpv ocrmypdf languagetool; do
    f=$t; [ $t = pdftotext ] && f=poppler; chk "$t" "brew install $f"
  done
  chk ollama "brew install ollama"
  chk pdf2zh_next "uv tool install --python 3.12 pdf2zh-next"
  chk whisper-cli "brew install whisper-cpp"
  m="$HOME/.local/opt/whisper.cpp/models/ggml-large-v3-turbo.bin"
  if [ -s "$m" ]; then ok "modèle $(du -h "$m" | cut -f1) $m"; else ko "modèle large-v3-turbo -> scripts/build-whisper.sh"; fi
  echo "[python 3.12]"
  if uv python find 3.12 >/dev/null 2>&1; then ok "$(uv python find 3.12)"; else ko "uv python install 3.12"; fi
  echo "[machine]"
  ok "$(sysctl -n machdep.cpu.brand_string 2>/dev/null), $(sysctl -n hw.ncpu) cœurs, $(( $(sysctl -n hw.memsize) / 1073741824 )) Go RAM ($(uname -m))"
  echo "[ollama]"
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    ok "serveur joignable"
    ollama list 2>/dev/null | sed 's/^/  model   /'
    ollama ps 2>/dev/null | sed 's/^/  ps      /'
  else ko "serveur injoignable -> brew services start ollama"; fi
  echo "[port]"
  if lsof -nP -iTCP:7777 -sTCP:LISTEN >/dev/null 2>&1; then ok "7777 occupé (atelier déjà lancé ?)"; else ok "7777 libre"; fi
  exit 0
fi

echo "[outils]"
chk uv "pacman -S uv"
chk yt-dlp "pacman -S yt-dlp"
chk ffmpeg "pacman -S ffmpeg"
chk xdg-open "pacman -S xdg-utils"
chk ollama "pacman -S ollama-vulkan (ou ollama-rocm)"
chk pdf2zh_next "uv tool install --python 3.12 pdf2zh-next"
if command -v whisper-cli >/dev/null 2>&1; then ok "whisper-cli ($(command -v whisper-cli))"
else ko "whisper-cli -> scripts/build-whisper.sh (build Vulkan, pas de paquet repo)"; fi
m="$HOME/.local/opt/whisper.cpp/models/ggml-large-v3-turbo.bin"
if [ -s "$m" ]; then ok "modèle $(du -h "$m" | cut -f1) $m"; else ko "modèle large-v3-turbo -> scripts/build-whisper.sh"; fi

echo "[python 3.12]"
if uv python find 3.12 >/dev/null 2>&1; then ok "$(uv python find 3.12)"; else ko "uv python install 3.12"; fi

echo "[gpu]"
best=""
for d in /sys/class/drm/card[0-9]*/device; do
  [ -r "$d/mem_info_vram_total" ] && best="$d"
done
if [ -n "$best" ]; then
  ok "amdgpu sysfs $best ($(( $(cat "$best/mem_info_vram_total") / 1048576 )) Mo)"
else ko "mem_info_vram_total introuvable"; fi
if command -v vulkaninfo >/dev/null 2>&1; then
  vulkaninfo --summary 2>/dev/null | grep -m1 deviceName | sed 's/^ */  vulkan  /'
else ko "vulkaninfo -> pacman -S vulkan-tools vulkan-radeon"; fi

echo "[ollama]"
pacman -Q ollama ollama-vulkan ollama-rocm 2>/dev/null | sed 's/^/  pkg     /'
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  ok "serveur joignable"
  ollama list 2>/dev/null | sed 's/^/  model   /'
  ollama ps 2>/dev/null | sed 's/^/  ps      /'
else ko "serveur injoignable -> systemctl enable --now ollama"; fi

echo "[port]"
if ss -ltn 2>/dev/null | grep -q ':7777 '; then ok "7777 occupé (atelier déjà lancé ?)"; else ok "7777 libre"; fi
