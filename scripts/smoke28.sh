#!/usr/bin/env bash
# Phase 28 — Diagnostic (zip sans secrets) et vérif de mise à jour opt-in. Hors-ligne.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/data"
cat > "$tmp/config.toml" <<TOML
[paths]
output = "$tmp/out"
data = "$tmp/data"
[ollama]
url = "http://user:hunter2@127.0.0.1:11434"
api_token = "SECRET-TOKEN-XYZ"
[translate]
password = "pw-123"
chunk_chars = 1234
TOML
python3 -c "print('\n'.join(f'line {i}' for i in range(1, 701)))" > "$tmp/data/atelier.log"
t "syntaxe" "python3 -m py_compile atelier/diagnostic.py atelier/config.py atelier/main.py"

PYTHONPATH=. ATELIER_CONFIG="$tmp/config.toml" uv run --frozen --offline python - "$tmp" <<'PY' >"$tmp/res.txt" 2>&1
import io, json, sys, zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from atelier.main import app
from atelier.diagnostic import clean_config

tmp = Path(sys.argv[1])
ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

cleaned = clean_config((tmp / "config.toml").read_text())
check("config: clés secrètes retirées", "SECRET-TOKEN-XYZ" not in cleaned and "pw-123" not in cleaned and "api_token" not in cleaned and "password" not in cleaned)
check("config: identifiants d'URL masqués", "hunter2" not in cleaned and "***@" in cleaned)
check("config: valeurs non secrètes gardées", "chunk_chars = 1234" in cleaned)
check("config: chemin HOME remplacé", str(Path.home()) not in clean_config(f"x = \"{Path.home()}/a\"\n") and "~/a" in clean_config(f"x = \"{Path.home()}/a\"\n"))

import urllib.request
from atelier import update
from atelier.config import cfg
calls = []
def no_net(*a, **k):
    calls.append(1); raise OSError("hors-ligne")
urllib.request.urlopen = no_net
update._cache.update(at=0.0)
check("update: désactivée par défaut, aucun appel réseau", cfg["update"]["check"] is False and update.check() == {"latest": None, "enabled": False} and not calls)
cfg["update"]["check"] = True
check("update: hors-ligne -> latest null", update.check()["latest"] is None and len(calls) == 1)
update._cache.update(at=0.0)
update._fetch = lambda: {"latest": "99.0.0", "url": "https://github.com/kerstz/atelier-hub/releases/tag/v99.0.0"}
r = update.check()
check("update: release plus récente -> newer + lien GitHub", r["newer"] and r["latest"] == "99.0.0" and r["url"].startswith("https://github.com/"))
update._cache.update(at=0.0); update.VERSION = "0.1.5"
update._fetch = lambda: {"latest": "0.1.5", "url": "https://github.com/x/y"}
check("update: même version -> pas de bannière", update.check()["newer"] is False)
update._cache.update(at=0.0)
update._fetch = lambda: {"latest": "0.2.0", "url": "https://github.com/x/y"}
check("update: 0.2.0 > 0.1.5", update.check()["newer"] is True)
update._cache.update(at=0.0); cfg["update"]["check"] = False
with TestClient(app, base_url="http://127.0.0.1:7777") as c:
    u = c.get("/api/update")
    check("update: route 200, inerte quand désactivée", u.status_code == 200 and u.json()["latest"] is None and len(calls) == 1)
    r = c.get("/api/diagnostic")
    check("diagnostic: 200 zip en pièce jointe", r.status_code == 200 and r.headers["content-type"] == "application/zip" and "attachment" in r.headers["content-disposition"])
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    check("diagnostic: diagnostic.json, config.toml, atelier.log", {"diagnostic.json", "config.toml", "atelier.log"} <= names)
    info = json.loads(z.read("diagnostic.json"))
    check("diagnostic: version et plateforme", bool(info["version"]) and info["plateforme"].startswith("linux"))
    check("diagnostic: deps présents/absents", info["deps"] and all(set(d) == {"id", "label", "present"} for d in info["deps"]))
    log = z.read("atelier.log").decode().splitlines()
    check("diagnostic: 500 dernières lignes du journal", len(log) == 500 and log[-1] == "line 700")
    blob = b"".join(z.read(n) for n in names)
    check("diagnostic: aucun secret ni chemin HOME dans l'archive", b"SECRET-TOKEN-XYZ" not in blob and b"hunter2" not in blob and str(Path.home()).encode() not in blob)
raise SystemExit(0 if ok else 1)
PY
rc=$?
cat "$tmp/res.txt"
t "diagnostic: tests Python" "[ $rc = 0 ]"
exit $fail
