#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
uv_bin="$(command -v uv)"
if [ "$(uname)" = Darwin ]; then
  # XML-escape, then escape for the sed replacement (\ | &)
  esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/[\\|&]/\\&/g'; }
  path="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  dest="$HOME/Library/LaunchAgents/fr.atelier.plist"
  dom="gui/$(id -u)"
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  sed -e "s|@ROOT@|$(esc "$root")|g" -e "s|@UV@|$(esc "$uv_bin")|g" -e "s|@HOME@|$(esc "$HOME")|g" \
    -e "s|@PATH@|$(esc "$path")|g" "$root/launchd/fr.atelier.plist.in" > "$dest"
  plutil -lint "$dest"
  launchctl bootout "$dom/fr.atelier" 2>/dev/null || true
  # bootout finishes asynchronously: bootstrap can fail (error 5) for a moment
  for i in 1 2 3 4 5; do launchctl bootstrap "$dom" "$dest" 2>/dev/null && break; [ "$i" = 5 ] && launchctl bootstrap "$dom" "$dest"; sleep 1; done
  launchctl kickstart -k "$dom/fr.atelier"
  launchctl print "$dom/fr.atelier" 2>/dev/null | grep -m2 -E 'state|pid' || true
  echo "logs: $HOME/Library/Logs/Atelier.log"
  exit 0
fi
dest="$HOME/.config/systemd/user"
mkdir -p "$dest"
sed -e "s|@ROOT@|$root|" -e "s|@UV@|$uv_bin|" "$root/systemd/atelier.service" > "$dest/atelier.service"
systemctl --user daemon-reload
systemctl --user enable --now atelier.service
systemctl --user --no-pager status atelier.service | head -5
