#!/usr/bin/env bash
# Construit VERT (AGPL-3.0) en site statique servi par Atelier sur /vert/. Hors-ligne ensuite.
# VERT_REF = commit testé; `VERT_REF=<sha|branche> ./scripts/build-vert.sh` pour tester une autre version.
set -euo pipefail
cd "$(dirname "$0")/.."
ref="${VERT_REF:-f5ecdec90d52fa84d5204fb59bb8da7d31e3704a}"
src="$HOME/.local/opt/VERT"
die() { echo "build VERT: $*" >&2; exit 1; }
need() { grep -qE -- "$2" "$1" || die "patch obsolète ($1: $2), VERT a changé en amont"; }

out="$(python3 -c 'from atelier.config import data_dir; print(data_dir() / "vert")')"
mkdir -p "$HOME/.local/opt"
[ -d "$src/.git" ] || git clone -q --no-checkout https://github.com/VERT-sh/VERT "$src"
cd "$src"
git reset -q --hard
git clean -fdxq -e node_modules
git fetch -q --depth 1 origin "$ref"
git checkout -qf FETCH_HEAD
sha="$(git rev-parse HEAD)"

# servi sous /vert (chemins absolus /_app/... -> /vert/_app/...)
sed -i 's|relative: false,|relative: false,\n\t\t\tbase: "/vert",|' svelte.config.js
sed -i 's|paths: {|prerender: { handleHttpError: "warn" },\n\t\tpaths: {|' svelte.config.js
need svelte.config.js 'base: "/vert"'
# liens/fetch absolus en dur de VERT -> sous /vert
grep -rlE 'goto\("/|href="/[^/]|"/(pandoc\.wasm|sw\.js|manifest\.json)' src \
  | xargs sed -i -E 's#goto\("/#goto("/vert/#g; s#href="/([^/])#href="/vert/\1#g; s#href="/"#href="/vert/"#g; s#"/(pandoc\.wasm|sw\.js|manifest\.json)"#"/vert/\1"#g'
need src/lib/converters/pandoc/pandoc.svelte.ts '"/vert/pandoc\.wasm"'
need src/routes/+layout.svelte '"/vert/manifest\.json"'
# hors-ligne: ni serveurs vertd publics ni service worker (scope / interdit sous /vert)
v=src/lib/sections/settings/vertdSettings.svelte.ts
sed -i -E '/url: "https:\/\/(eu|usa)\.vertd\.vert\.sh"/d; s#return "https://(eu|usa)\.vertd\.vert\.sh";#throw new Error("vertd distant désactivé");#' $v
sed -i 's#error(\["vertd"\], `failed to resolve vertd size limit#log(["vertd"], `failed to resolve vertd size limit#' $v
! grep -qE '(eu|usa)\.vertd\.vert\.sh' $v || die "patch obsolète ($v: serveurs vertd publics)"
sed -i 's#if (!browser || !("serviceWorker"#if (true || !browser || !("serviceWorker"#' src/lib/util/sw.ts
need src/lib/util/sw.ts 'if \(true \|\|'
# thème: même clé localStorage "theme" qu'Atelier, ne pas la figer au 1er chargement
sed -i '/localStorage.setItem("theme", theme);/d' src/app.html
! grep -q 'localStorage.setItem("theme", theme);' src/app.html || die "patch obsolète (src/app.html: thème)"
# fichiers produits: nom d'origine, sans préfixe "VERT_"
grep -rl '"VERT_%name%"' src | xargs -r sed -i 's#"VERT_%name%"#"%name%"#g'
! grep -rq '"VERT_%name%"' src || die "patch obsolète (préfixe VERT_)"
export PUB_ENV=production PUB_HOSTNAME=localhost PUB_DISABLE_ALL_EXTERNAL_REQUESTS=true PUB_DISABLE_FAILURE_BLOCKS=true
# $env/static/public exige toutes les variables, même vides (pas de vertd distant, pas de dons/stats)
export PUB_VERTD_URL= PUB_PLAUSIBLE_URL= PUB_DONATION_URL= PUB_DONATION_API= PUB_STRIPE_KEY=
# ffmpeg.wasm servi localement (VERT le charge sinon depuis cdn.jsdelivr.net)
ff=src/lib/converters/ffmpeg/ffmpeg.svelte.ts
ffv="$(grep -oP '@ffmpeg/core@\K[0-9.]+' "$ff" | head -1)"
[ -n "$ffv" ] || die "patch obsolète ($ff: version @ffmpeg/core)"
sed -i -E 's#https://cdn\.jsdelivr\.net/npm/@ffmpeg/core@[0-9.]+/dist/esm#/vert/ffmpeg#g' "$ff"
need "$ff" '/vert/ffmpeg'
if command -v bun >/dev/null; then
  bun install --frozen-lockfile --ignore-scripts
  bun add -d --ignore-scripts "@ffmpeg/core@$ffv"
else
  echo "bun absent: repli npm, build non reproductible (plages ^ résolues à la volée)" >&2
  npm install --legacy-peer-deps --ignore-scripts --no-audit --no-fund
  npm install --no-save --legacy-peer-deps --ignore-scripts --no-audit --no-fund "@ffmpeg/core@$ffv"
fi
mkdir -p static/ffmpeg
cp node_modules/@ffmpeg/core/dist/esm/ffmpeg-core.{js,wasm} static/ffmpeg/
if command -v bun >/dev/null; then bun run build; else npm run build; fi
[ -f build/index.html ] || die "build/index.html absent"
grep -q '/vert/_app/' build/index.html || die "base /vert absente du build"
rm -f build/sw.js
! grep -rqE 'cdn\.jsdelivr\.net/npm/@ffmpeg|vertd\.vert\.sh' build/_app || die "URL externe restante (ffmpeg/vertd)"
cp LICENSE build/LICENSE.VERT
printf 'VERT https://github.com/VERT-sh/VERT %s (AGPL-3.0)\nPatches: scripts/build-vert.sh du dépôt Atelier\n' "$sha" > build/SOURCE
rm -rf "$out.new"
cp -a build "$out.new"
rm -rf "$out"
mv "$out.new" "$out"
echo "ok -> $out (redémarre Atelier: systemctl --user restart atelier)"
