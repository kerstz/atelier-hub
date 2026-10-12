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
if command -v dpkg-deb >/dev/null; then
  t "paquet factice" "d=\$(mktemp -d); mkdir -p dist/Atelier && printf '#!/bin/sh\n' > dist/Atelier/Atelier && chmod +x dist/Atelier/Atelier && bash scripts/build-deb.sh 9.9.9 && dpkg-deb -c dist/atelier_9.9.9_amd64.deb | grep -q usr/bin/atelier; rc=\$?; rm -rf dist/Atelier dist/deb dist/atelier_9.9.9_amd64.deb; exit \$rc"
else
  echo "skip paquet factice (dpkg-deb absent)"
fi
[ $fail = 0 ] && echo "smoke24 ok"
exit $fail
