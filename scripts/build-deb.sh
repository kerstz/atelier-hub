#!/usr/bin/env bash
# dist/Atelier (PyInstaller onedir, Linux) -> dist/atelier_<version>_amd64.deb
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
ver="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/pyproject.toml" | head -1)}"
ver="${ver#v}"
# a dpkg version starts with a digit: a manual run on a branch (GITHUB_REF_NAME=main) falls back to pyproject's
[[ $ver =~ ^[0-9][A-Za-z0-9.+~-]*$ ]] || ver="$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/pyproject.toml" | head -1)~${ver//[^A-Za-z0-9]/}"
src="$root/dist/Atelier"
[ -x "$src/Atelier" ] || { echo "build PyInstaller d'abord: $src/Atelier introuvable" >&2; exit 1; }
pkg="$root/dist/deb"
rm -rf "$pkg"
install -d "$pkg/DEBIAN" "$pkg/opt" "$pkg/usr/bin" "$pkg/usr/lib/systemd/user" "$pkg/usr/share/applications" "$pkg/usr/share/icons/hicolor/scalable/apps"
cp -a "$src" "$pkg/opt/atelier"
install -m755 "$root/packaging/deb/atelier" "$pkg/usr/bin/atelier"
install -m644 "$root/packaging/deb/atelier.service" "$pkg/usr/lib/systemd/user/atelier.service"
install -m644 "$root/packaging/deb/atelier.desktop" "$pkg/usr/share/applications/atelier.desktop"
install -m644 "$root/static/icon.svg" "$pkg/usr/share/icons/hicolor/scalable/apps/atelier.svg"
install -d "$pkg/opt/atelier/scripts"  # plat.localize points the setup hints here
install -m755 "$root"/scripts/{build-whisper,fix-pdf2zh,voice-setup,voice-refs,get-languagetool}.sh "$pkg/opt/atelier/scripts/"
size=$(du -sk "$pkg" | cut -f1)
cat > "$pkg/DEBIAN/control" <<CTL
Package: atelier
Version: $ver
Architecture: amd64
Maintainer: Atelier <noreply@localhost>
Installed-Size: $size
Depends: libc6 (>= 2.35), xdg-utils
Recommends: ffmpeg, yt-dlp
Suggests: ocrmypdf, mpv
Section: utils
Priority: optional
Description: Hub local de traduction, médias et documents
 Traduction, YouTube, sous-titres, documents, conversion. Hors ligne,
 écoute sur 127.0.0.1:7777. Lancer avec la commande "atelier".
CTL
dpkg-deb --root-owner-group --build "$pkg" "$root/dist/atelier_${ver}_amd64.deb" >/dev/null
echo "ok dist/atelier_${ver}_amd64.deb"
