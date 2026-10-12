#!/usr/bin/env bash
# Phase 23 — Windows: branches plateforme simulées (ATELIER_FAKE_WIN=1), démarrage headless du lanceur, régression Linux.
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"; [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null' EXIT
py() { uv run --frozen --offline python "$@"; }
export PYTHONPATH=.

t "compile: plat, winlaunch, spec, lanceur" "py -m py_compile atelier/plat.py atelier/winlaunch.py scripts/atelier_win.py && py -c \"compile(open('packaging/atelier.spec').read(),'spec','exec')\""
t "Linux: spawn_kw = start_new_session" "py -c \"from atelier import plat; assert plat.spawn_kw()=={'start_new_session':True}; assert plat.open_folder_argv('/x')==['xdg-open','/x']\""
t "Windows simulé: spawn_kw, explorer, venv" "ATELIER_FAKE_WIN=1 py -c \"
from atelier import plat
k=plat.spawn_kw(); assert k['creationflags']==0x200|0x08000000 and 'start_new_session' not in k
assert plat.open_folder_argv('C:/x')==['explorer','C:/x']
assert plat.venv_python('~/v')=='~/v/Scripts/python.exe'\""
t "Windows simulé: chemins remappés, pas de vaapi" "ATELIER_FAKE_WIN=1 ATELIER_CONFIG=/nonexistent py -c \"
from atelier.config import cfg
assert cfg['paths']['data']=='~/AppData/Local/Atelier', cfg['paths']
assert cfg['whisper']['model'].startswith('~/AppData/Local/Atelier/opt/whisper.cpp'), cfg['whisper']
assert cfg['voice']['python']=='~/AppData/Local/Atelier/seedvc-venv/Scripts/python.exe', cfg['voice']['python']
assert cfg['paths']['output']=='~/Atelier'
from atelier import convert; assert convert.vaapi_ok() is False\""
t "Windows simulé: config.toml du dépôt remappé aussi" "ATELIER_FAKE_WIN=1 py -c \"
from atelier.config import cfg
assert cfg['paths']['data'].startswith('~/AppData/Local/Atelier'), cfg['paths']
assert cfg['convert']['vaapi_device']==''\""
t "Windows simulé: services sans systemd" "ATELIER_FAKE_WIN=1 py -c \"
from atelier import services
assert services._control({'unit':'x'}) is None and services._control({'dir':'/d'})=='compose'\""
t "Windows simulé: conseils winget" "ATELIER_FAKE_WIN=1 py -c \"
from atelier import maint
assert maint._win_hint('sudo pacman -S ffmpeg')=='winget install Gyan.FFmpeg'
assert 'pacman' not in maint._win_hint('sudo pacman -S libvips')\""
t "Windows: parse GPU (objet unique, liste, vide)" "py - <<'PY'
import json
from atelier import plat
one = json.dumps({'cards': {'name': 'AMD Radeon RX 6900 XT', 'total': 17163091968, 'dev': 'PCI\\\\VEN_1002&DEV_73BF'}, 'used': 2147483648})
g = plat.parse_win_gpus(one); assert len(g) == 1 and g[0]['vendor'] == 'amd' and g[0]['used'] == 2147483648 and g[0]['total'] == 17163091968, g
two = json.dumps({'cards': [{'name': 'Intel UHD', 'total': 134217728, 'dev': 'PCI\\\\VEN_8086&DEV_1'}, {'name': 'RTX', 'total': 8589934592, 'dev': 'PCI\\\\VEN_10DE&DEV_2'}], 'used': 1000})
g = plat.parse_win_gpus(two); assert [x['vendor'] for x in g] == ['intel', 'nvidia'] and g[1]['used'] == 1000 and g[0]['used'] == 0, g
assert plat.parse_win_gpus('') == [] and plat.parse_win_gpus('{\"cards\":null,\"used\":0}') == []
PY"
t "Linux: remap neutre sans IS_WIN" "py -c \"
from atelier.config import cfg
from atelier import plat
assert plat.remap('~/.local/opt/x')=='~/AppData/Local/Atelier/opt/x' and plat.remap('/usr/bin/x')=='/usr/bin/x' and plat.remap('~/.local/optical')=='~/.local/optical'\""
t "kill_tree: tue le groupe (Linux)" "py - <<'PY'
import asyncio, time
from atelier import plat
async def main():
    p = await asyncio.create_subprocess_exec('bash','-c','sleep 60 & sleep 60', **plat.spawn_kw())
    await asyncio.sleep(0.3); plat.kill_tree(p)
    await asyncio.wait_for(p.wait(), 3); assert p.returncode is not None
asyncio.run(main())
PY"
t "run_cmd: annulation tue l'enfant" "py - <<'PY'
import asyncio
from atelier.proc import run_cmd
async def main():
    t = asyncio.create_task(run_cmd(['sleep','60'])); await asyncio.sleep(0.4); t.cancel()
    try: await t
    except asyncio.CancelledError: pass
    else: raise SystemExit(1)
asyncio.run(main())
PY"

# lanceur: serveur dans un thread, mode sans fenêtre, config isolée
cat > "$tmp/c.toml" <<T
[server]
port = 7793
[paths]
output = "$tmp/out"
data = "$tmp/data"
T
ATELIER_CONFIG="$tmp/c.toml" ATELIER_NO_WINDOW=1 uv run --frozen --offline python scripts/atelier_win.py >"$tmp/l.log" 2>&1 &
pid=$!
t "lanceur: / et /api/system répondent (mode sans fenêtre)" "for i in \$(seq 40); do curl -sf http://127.0.0.1:7793/api/system >/dev/null && break; sleep 0.5; done; curl -sf http://127.0.0.1:7793/ | grep -qi '<html' && curl -sf http://127.0.0.1:7793/api/system | grep -q vram"
t "lanceur: 2e instance sort tout de suite" "ATELIER_CONFIG='$tmp/c.toml' BROWSER=true timeout 10 uv run --frozen --offline python scripts/atelier_win.py"
kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; pid=
t "CI: job windows présent" "grep -q windows-latest .github/workflows/ci.yml"
exit $fail
