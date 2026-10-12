#!/usr/bin/env bash
# Installe l'entrée de menu Atelier (idempotent). Aucun droit root.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
venv="${ATELIER_DESKTOP_VENV:-$data/atelier/desktop-venv}"
apps="$data/applications"
icons="$data/icons/hicolor/scalable/apps"
wmclass="${ATELIER_WMCLASS:-atelier}"

chmod +x "$root/scripts/atelier-desktop" "$root/scripts/atelier_desktop.py"

# venv fenêtre: python système (gi / PyQt6 de pacman) + pywebview du groupe "desktop"
if [ ! -x "$venv/bin/python" ]; then
  uv venv --quiet --system-site-packages --python /usr/bin/python3 "$venv"
fi
uv pip install --quiet --python "$venv/bin/python" --group "$root/pyproject.toml:desktop"

case "${XDG_CURRENT_DESKTOP:-}" in
  *[Kk][Dd][Ee]*|*[Pp]lasma*) probe="from qtpy import QtWebEngineWidgets"; need="python-pyqt6-webengine python-qtpy" ;;
  *) probe="import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')"; need="python-gobject webkit2gtk-4.1 gtk3" ;;
esac
"$venv/bin/python" -c "$probe" 2>/dev/null || echo "avertissement: backend graphique incomplet: sudo pacman -S $need (repli navigateur en attendant)"

mkdir -p "$apps" "$icons"
install -m 644 "$root/static/icon.svg" "$icons/atelier.svg"
sed -e "s|@ROOT@|$root|g" -e "s|@WMCLASS@|$wmclass|" "$root/desktop/atelier.desktop.in" > "$apps/atelier.desktop.tmp"
mv "$apps/atelier.desktop.tmp" "$apps/atelier.desktop"
chmod 644 "$apps/atelier.desktop"

command -v desktop-file-validate >/dev/null && desktop-file-validate "$apps/atelier.desktop"
update-desktop-database "$apps" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$data/icons/hicolor" 2>/dev/null || true
echo "ok: $apps/atelier.desktop (StartupWMClass=$wmclass)"
