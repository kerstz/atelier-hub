#!/usr/bin/env bash
# Construit Harper (Apache-2.0, vérificateur anglais en WASM) en un seul fichier servi sur /harper/harper.js. Hors-ligne ensuite.
# HARPER_VER = version testée de harper.js; `HARPER_VER=x.y.z ./scripts/build-harper.sh` pour une autre.
set -euo pipefail
cd "$(dirname "$0")/.."
ver="${HARPER_VER:-2.13.0}"
die() { echo "build Harper: $*" >&2; exit 1; }
command -v npm >/dev/null || die "npm absent (sudo pacman -S npm)"

# HARPER_OUT=static/harper pour embarquer dans les releases (.exe/.deb)
out="${HARPER_OUT:-$(uv run --frozen --offline python -c 'from atelier.config import data_dir; print(data_dir() / "harper")' 2>/dev/null || echo "$HOME/.local/share/atelier/harper")}"
work="$HOME/.local/opt/harper-build"
mkdir -p "$work" "$out"
out="$(cd "$out" && pwd)"
cp scripts/harper/entry.js "$work/entry.js"
cd "$work"
[ -f package.json ] || echo '{"private":true}' > package.json
npm install --save-exact --ignore-scripts --no-audit --no-fund --silent "harper.js@$ver" esbuild@0.25.0
./node_modules/.bin/esbuild entry.js --bundle --minify --format=iife --external:fs --external:module --external:path --external:url --outfile="$out/harper.js.new" --log-level=warning
[ -s "$out/harper.js.new" ] || die "bundle vide"
mv "$out/harper.js.new" "$out/harper.js"
cp node_modules/harper.js/dist/harper_wasm_bg.wasm "$out/harper.wasm"
cp node_modules/harper.js/LICENSE "$out/LICENSE.harper"
echo "harper.js $ver" > "$out/VERSION"
echo "ok: $out/harper.js ($(du -h "$out/harper.js" | cut -f1))"
