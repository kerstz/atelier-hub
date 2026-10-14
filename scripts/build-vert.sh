#!/usr/bin/env bash
# Construit VERT (AGPL-3.0) en site statique servi par Atelier sur /vert/. Hors-ligne ensuite.
set -euo pipefail
src="$HOME/.local/opt/VERT"
out="$(python3 - <<'P'
import tomllib, pathlib
c = tomllib.loads(pathlib.Path("config.toml").read_text())
print(pathlib.Path(c["paths"]["data"]).expanduser() / "vert")
P
)"
mkdir -p "$HOME/.local/opt"
if [ ! -d "$src/.git" ]; then
  git clone --depth 1 https://github.com/VERT-sh/VERT "$src"
else
  git -C "$src" pull --ff-only -q
fi
cd "$src"
git checkout -q -- .
# servi sous /vert (chemins absolus /_app/... -> /vert/_app/...)
sed -i 's|relative: false,|relative: false,\n\t\t\tbase: "/vert",|' svelte.config.js
sed -i 's|paths: {|prerender: { handleHttpError: "warn" },\n\t\tpaths: {|' svelte.config.js
# liens/fetch absolus en dur de VERT -> sous /vert
grep -rlE 'goto\("/|href="/[^/]|"/(pandoc\.wasm|sw\.js|manifest\.json)' src \
  | xargs sed -i -E 's#goto\("/#goto("/vert/#g; s#href="/([^/])#href="/vert/\1#g; s#href="/"#href="/vert/"#g; s#"/(pandoc\.wasm|sw\.js|manifest\.json)"#"/vert/\1"#g'
# hors-ligne: ni serveurs vertd publics ni service worker (scope / interdit sous /vert)
sed -i -E '/url: "https:\/\/(eu|usa)\.vertd\.vert\.sh"/d; s#return "https://(eu|usa)\.vertd\.vert\.sh";#throw new Error("vertd distant désactivé");#' src/lib/sections/settings/vertdSettings.svelte.ts
sed -i 's#error(\["vertd"\], `failed to resolve vertd size limit#log(["vertd"], `failed to resolve vertd size limit#' src/lib/sections/settings/vertdSettings.svelte.ts
sed -i 's#if (!browser || !("serviceWorker"#if (true || !browser || !("serviceWorker"#' src/lib/util/sw.ts
# thème: même clé localStorage "theme" qu'Atelier, ne pas la figer au 1er chargement
sed -i '/localStorage.setItem("theme", theme);/d' src/app.html
# fichiers produits: nom d'origine, sans préfixe "VERT_"
grep -rl '"VERT_%name%"' src | xargs sed -i 's#"VERT_%name%"#"%name%"#g'
export PUB_ENV=production PUB_HOSTNAME=localhost PUB_DISABLE_ALL_EXTERNAL_REQUESTS=true PUB_DISABLE_FAILURE_BLOCKS=true
# $env/static/public exige toutes les variables, même vides (pas de vertd distant, pas de dons/stats)
export PUB_VERTD_URL= PUB_PLAUSIBLE_URL= PUB_DONATION_URL= PUB_DONATION_API= PUB_STRIPE_KEY=
# ffmpeg.wasm servi localement (VERT le charge sinon depuis cdn.jsdelivr.net)
ff=src/lib/converters/ffmpeg/ffmpeg.svelte.ts
ffv="$(grep -oP '@ffmpeg/core@\K[0-9.]+' "$ff" | head -1)"
sed -i -E 's#https://cdn\.jsdelivr\.net/npm/@ffmpeg/core@[0-9.]+/dist/esm#/vert/ffmpeg#g' "$ff"
if command -v bun >/dev/null; then
  bun install
  bun add -d "@ffmpeg/core@$ffv"
else
  npm install --legacy-peer-deps --no-audit --no-fund
  npm install --no-save --legacy-peer-deps --no-audit --no-fund "@ffmpeg/core@$ffv"
fi
mkdir -p static/ffmpeg
cp node_modules/@ffmpeg/core/dist/esm/ffmpeg-core.{js,wasm} static/ffmpeg/
if command -v bun >/dev/null; then bun run build; else npm run build; fi
if grep -rqE 'cdn\.jsdelivr\.net/npm/@ffmpeg|vertd\.vert\.sh' build/_app; then
  echo "build VERT: URL externe restante (ffmpeg/vertd)" >&2
  exit 1
fi
[ -f build/index.html ] || { echo "build VERT: build/index.html absent" >&2; exit 1; }
rm -rf "$out"
mkdir -p "$out"
cp -a build/. "$out"/
echo "ok -> $out (redémarre Atelier: systemctl --user restart atelier)"
