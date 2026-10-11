#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
uv_bin="$(command -v uv)"
dest="$HOME/.config/systemd/user"
mkdir -p "$dest"
sed -e "s|@ROOT@|$root|" -e "s|@UV@|$uv_bin|" "$root/systemd/atelier.service" > "$dest/atelier.service"
systemctl --user daemon-reload
systemctl --user enable --now atelier.service
systemctl --user --no-pager status atelier.service | head -5
