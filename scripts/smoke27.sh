#!/usr/bin/env bash
# Phase 27 — port macOS: plateforme (ATELIER_FAKE_MAC=1), hints brew, installeur launchd, plist. Hors-ligne, sans service.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
mac() { ATELIER_FAKE_MAC=1 PYTHONPATH=. uv run --frozen --offline python -c "$1"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

t "plat: open_folder_argv = open" 'mac "from atelier import plat; assert plat.open_folder_argv(\"/x\")==[\"open\",\"/x\"]"'
t "plat: distro() == mac" 'mac "from atelier import plat; assert plat.distro()==\"mac\""'
t "plat: notify_argv forme osascript + argv après --" 'mac "from atelier import plat; a=plat.notify_argv(\"T\",\"B\"); assert a[0]==\"osascript\"; assert a[-3:]==[\"--\",\"T\",\"B\"]"'
t "plat: notify_argv n'interpole pas le texte" 'mac "from atelier import plat; x=\"x\\\" & do shell script \\\"id\\\"\"; a=plat.notify_argv(x,\"b\"); assert not any(x in s for s in a[:-3]); assert a[-2]==x"'
t "maint: formules brew + casks séparés" 'mac "from atelier import maint; h=maint._linux_hint(\"sudo pacman -S ffmpeg calibre libreoffice-fresh poppler\",\"mac\"); assert h==\"brew install ffmpeg poppler && brew install --cask calibre libreoffice\", h"'
t "maint: ollama -> brew services" 'mac "from atelier import maint; assert maint._mac_hint(\"sudo systemctl start ollama\")==\"brew services start ollama\""'
t "maint: localize pacman -> brew" 'mac "from atelier import plat; assert plat.localize(\"sudo pacman -S yt-dlp\")==\"brew install yt-dlp\", plat.localize(\"sudo pacman -S yt-dlp\")"'
t "convert: videotoolbox présent" 'grep -q videotoolbox atelier/convert.py'
t "parse_vm_stat: free+inactive+speculative x page" 'mac "from atelier import plat; s=\"Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:  1000.\nPages active: 5.\nPages inactive: 2000.\nPages speculative: 500.\"; assert plat.parse_vm_stat(s)==3500*16384"'
t "parse_vm_stat: texte vide -> 0" 'mac "from atelier import plat; assert plat.parse_vm_stat(\"\")==0"'
t "parse_mac_gpu: Apple silicon 2/3 RAM" 'mac "from atelier import plat; g=plat.parse_mac_gpu(str(16*2**30),\"Apple M1\",True); assert g[\"vendor\"]==\"apple\" and g[\"vram_total\"]==int(16*2**30*0.66)"'
t "parse_mac_gpu: Intel / invalide -> None" 'mac "from atelier import plat; assert plat.parse_mac_gpu(str(2**34),\"Intel\",False) is None; assert plat.parse_mac_gpu(\"n/a\",\"\",True) is None"'
t "services: clé brew -> brew services" 'mac "from atelier import services as s; assert s._control({\"brew\":\"ollama\",\"port\":1})==\"brew\"; assert s._argv({\"brew\":\"ollama\",\"port\":1},\"start\")==[\"brew\",\"services\",\"start\",\"ollama\"]"'
t "install.sh: bash -n (bash + /bin/bash)" 'for f in install.sh scripts/install-mac.sh scripts/install-service.sh scripts/build-whisper.sh scripts/env-check.sh; do bash -n $f && /bin/bash -n $f || exit 1; done'
t "install-mac.sh --dry-run (ATELIER_FAKE_DARWIN) rc 0 et cite brew" 'ATELIER_FAKE_DARWIN=1 bash scripts/install-mac.sh --dry-run --yes > $tmp/dry.txt 2>&1; rc=$?; [ $rc = 0 ] && grep -qi brew $tmp/dry.txt'
t "plist: rendu sed + plistlib" 'sed -e "s|@UV@|/usr/bin/uv|g" -e "s|@ROOT@|$PWD|g" -e "s|@HOME@|$HOME|g" -e "s|@PATH@|/opt/homebrew/bin:/usr/bin:/bin|g" launchd/fr.atelier.plist.in > $tmp/fr.atelier.plist && uv run --frozen --offline python -c "import plistlib,sys; d=plistlib.load(open(sys.argv[1],\"rb\")); assert d[\"Label\"]==\"fr.atelier\"; assert \"@\" not in str(d)" $tmp/fr.atelier.plist'

if [ "$(uname)" = Darwin ]; then
  t "hw.detect: RAM > 0 (Mac réel)" 'PYTHONPATH=. uv run --frozen --offline python -c "from atelier import hw; assert hw.detect()[\"ram_total\"]>0"'
  t "plist: plutil -lint (Mac réel)" 'sed -e "s|@UV@|$(command -v uv)|g" -e "s|@ROOT@|$PWD|g" -e "s|@HOME@|$HOME|g" -e "s|@PATH@|/usr/bin:/bin|g" launchd/fr.atelier.plist.in > $tmp/real.plist && plutil -lint $tmp/real.plist'
else
  echo "skip checks Mac réel (uname=$(uname))"
fi
exit $fail
