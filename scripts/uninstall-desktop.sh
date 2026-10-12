#!/usr/bin/env bash
# Retire l'entrée de menu Atelier (idempotent). --purge: aussi le venv fenêtre et la géométrie mémorisée.
set -u
data="${XDG_DATA_HOME:-$HOME/.local/share}"
venv="${ATELIER_DESKTOP_VENV:-$data/atelier/desktop-venv}"
apps="$data/applications"
rm -f "$apps/atelier.desktop" "$data/icons/hicolor/scalable/apps/atelier.svg"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$venv"
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/atelier/window.json"
fi
update-desktop-database "$apps" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$data/icons/hicolor" 2>/dev/null || true
echo "ok: entrée de menu retirée"
