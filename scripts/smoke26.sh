#!/usr/bin/env bash
# Phase 26 — Correcteur: Harper (EN, navigateur) + LanguageTool (FR, local). LT saute si absent.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
B=http://127.0.0.1:7777
t "build-harper.sh: syntaxe" "bash -n scripts/build-harper.sh"
t "grammar.js: syntaxe" "node --check static/grammar.js"
t "status" "curl -sf $B/api/grammar/status | grep -q lt_available"
t "langue inconnue refusée" "[ \$(curl -s -o /dev/null -w '%{http_code}' -XPOST $B/api/grammar/check -H 'content-type: application/json' -d '{\"text\":\"a\",\"lang\":\"xx\"}') = 400 ]"
if curl -sf $B/api/grammar/status | grep -q '"harper":true'; then
  t "harper.wasm servi" "curl -sf -o /dev/null $B/harper/harper.wasm"
else echo "skip Harper non construit: ./scripts/build-harper.sh"; fi
if curl -sf $B/api/grammar/status | grep -q '"lt_available":true'; then
  t "LanguageTool trouve une faute FR" "curl -sf -XPOST $B/api/grammar/check -H 'content-type: application/json' -d '{\"text\":\"Les chat mange des souris.\",\"lang\":\"fr\"}' | grep -q offset"
else echo "skip LanguageTool absent: sudo pacman -S languagetool"; fi
exit $fail
