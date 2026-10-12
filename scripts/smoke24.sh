#!/usr/bin/env bash
# Phase 24 — release .deb: scripts parse, spec compile, config utilisateur binaire gelé, paquet factice (si dpkg-deb).
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { uv run --frozen --offline python "$@"; }
export PYTHONPATH=.

t "bash -n build-deb + lanceur" "bash -n scripts/build-deb.sh && bash -n packaging/deb/atelier"
t "spec compile" "py -c \"compile(open('packaging/atelier.spec').read(),'spec','exec')\""
t "workflow release: jobs deb + windows" "grep -q '^  deb:' .github/workflows/release.yml && grep -q '^  windows:' .github/workflows/release.yml"
osr=$(mktemp); printf 'ID=ubuntu\nID_LIKE=debian\n' > "$osr"
t "conseils apt sous Debian/Ubuntu" "ATELIER_OS_RELEASE=$osr py -c \"
from atelier import maint, plat
assert maint.distro_family('$osr') == 'debian'
assert plat.localize('sudo pacman -S tesseract tesseract-data-fra') == 'sudo apt install tesseract-ocr tesseract-ocr-fra'
assert plat.localize('x: sudo pacman -S poppler') == 'x: sudo apt install poppler-utils'
assert 'pipx install yt-dlp' in plat.localize('sudo pacman -S yt-dlp')\""
t "binaire gelé: scripts/ -> /opt/atelier/scripts" "d=\$(mktemp -d); mkdir \$d/scripts; touch \$d/scripts/build-whisper.sh; py -c \"
import sys; from atelier import plat
plat.FROZEN, sys.executable = True, '\$d/Atelier'
assert plat.localize('absent: scripts/build-whisper.sh') == 'absent: bash \$d/scripts/build-whisper.sh', plat.localize('absent: scripts/build-whisper.sh')
assert 'page du projet' in plat.localize('scripts/voice-setup.sh')\"; rc=\$?; rm -rf \$d; exit \$rc"
rm -f "$osr"
t "windows: win_args entre guillemets, upload verrouillé toléré" "ATELIER_FAKE_WIN=1 py -c \"
import pathlib
from atelier import services, util
from atelier.config import data_dir
a = services._win_argv({'win_exe': 'C:/x/app.exe', 'win_args': '--dir \\\"C:/My Files\\\" -v'}, 'start')
assert a == ['C:/x/app.exe', '--dir', 'C:/My Files', '-v'], a
def locked(self, missing_ok=False): raise PermissionError(32, 'Violation de partage')
pathlib.Path.unlink = locked
util.consume_uploads({'path': str(data_dir() / 'uploads' / 'x.wav')})\""
command -v desktop-file-validate >/dev/null && t "desktop-file-validate" "[ -z \"\$(desktop-file-validate packaging/deb/atelier.desktop)\" ]"
if command -v dpkg-deb >/dev/null; then
  t "paquet factice" "d=\$(mktemp -d); mkdir -p dist/Atelier && printf '#!/bin/sh\n' > dist/Atelier/Atelier && chmod +x dist/Atelier/Atelier && bash scripts/build-deb.sh 9.9.9 && dpkg-deb -c dist/atelier_9.9.9_amd64.deb | grep -q usr/bin/atelier; rc=\$?; rm -rf dist/Atelier dist/deb dist/atelier_9.9.9_amd64.deb; exit \$rc"
else
  echo "skip paquet factice (dpkg-deb absent)"
fi
[ $fail = 0 ] && echo "smoke24 ok"
exit $fail
