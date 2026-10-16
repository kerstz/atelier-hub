#!/usr/bin/env bash
# Télécharge LanguageTool (LGPL-2.1, ~250 Mo) dans le dossier de données d'Atelier. Linux, macOS, .deb.
# Alternatives: Arch `sudo pacman -S languagetool`, macOS `brew install languagetool`.
# LT_VER = version testée; `LT_VER=x.y ./scripts/get-languagetool.sh` pour une autre.
set -euo pipefail
cd "$(dirname "$0")/.." 2>/dev/null || true
ver="${LT_VER:-6.6}"
command -v java >/dev/null || { echo "Java absent: sudo pacman -S jre-openjdk | sudo apt install default-jre | brew install openjdk" >&2; exit 1; }
command -v unzip >/dev/null || { echo "unzip absent" >&2; exit 1; }
dest="$(python3 -c 'from atelier.config import data_dir; print(data_dir() / "languagetool")' 2>/dev/null || echo "$HOME/.local/share/atelier/languagetool")"
mkdir -p "$dest"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --progress-bar -o "$tmp/lt.zip" "https://languagetool.org/download/LanguageTool-$ver.zip"
unzip -q "$tmp/lt.zip" -d "$dest"
[ -f "$dest/LanguageTool-$ver/languagetool-server.jar" ] || { echo "archive inattendue" >&2; exit 1; }
echo "ok: $dest/LanguageTool-$ver"
