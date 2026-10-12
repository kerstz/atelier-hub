#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
root="$PWD"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
L="bash scripts/atelier-desktop"
real_venv="${ATELIER_DESKTOP_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/atelier/desktop-venv}"

# --- lanceur (dry-run: ne démarre rien)
t "bash -n lanceur" "bash -n scripts/atelier-desktop"
t "option inconnue -> 64" "$L --nope >/dev/null 2>&1; [ \$? = 64 ]"
t "gtk par défaut (Hyprland)" "XDG_CURRENT_DESKTOP=Hyprland $L --dry-run | grep -qx gui=gtk"
t "GNOME -> gtk" "XDG_CURRENT_DESKTOP=GNOME $L --dry-run | grep -qx gui=gtk"
t "KDE -> qt" "XDG_CURRENT_DESKTOP=KDE $L --dry-run | grep -qx gui=qt"
t "plasma:kde -> qt" "XDG_CURRENT_DESKTOP=plasma:KDE $L --dry-run | grep -qx gui=qt"
t "port via ATELIER_PORT" "ATELIER_PORT=9999 $L --dry-run | grep -qx url=http://127.0.0.1:9999/"
t "traduire: texte encodé en hash" "ATELIER_CLIP='Bonjour & monde' $L --translate-clipboard --dry-run | grep -qx 'hash=traduire?text=Bonjour%20%26%20monde'"
t "traduire: coupé à 4000 car." "[ \$(ATELIER_CLIP=\$(head -c 9000 /dev/zero | tr '\\0' a) $L --translate-clipboard --dry-run | grep ^hash= | wc -c) -lt 4100 ]"
t "traduire: presse-papiers vide -> pas de fenêtre" "ATELIER_CLIP='  ' $L --translate-clipboard --dry-run | grep -qx clipboard=vide"
t "télécharger: URL -> onglet youtube" "ATELIER_CLIP='https://youtu.be/abc?t=5' $L --download-clipboard --dry-run | grep -qx 'hash=youtube?url=https%3A%2F%2Fyoutu.be%2Fabc%3Ft%3D5'"
t "télécharger: non-URL refusé" "ATELIER_CLIP='bonjour' $L --download-clipboard --dry-run | grep -qx clipboard=pas-une-url"
t "sans venv fenêtre -> repli navigateur" "ATELIER_DESKTOP_VENV=$tmp/nope $L --dry-run | grep -Eq '^mode=(chromium|firefox)$'"
t "--browser force le repli" "$L --browser --dry-run | grep -Eq '^mode=(chromium|firefox)$'"
t "dry-run: service signalé" "$L --dry-run | grep -q '^service='"

# --- fichier .desktop
export XDG_DATA_HOME="$tmp/data" XDG_CONFIG_HOME="$tmp/cfg" ATELIER_DESKTOP_VENV="$real_venv"
if [ -x "$real_venv/bin/python" ]; then
  t "install-desktop.sh" "bash scripts/install-desktop.sh >/dev/null 2>&1"
  t "install idempotent" "bash scripts/install-desktop.sh >/dev/null 2>&1"
  f="$XDG_DATA_HOME/applications/atelier.desktop"
  t "desktop-file-validate" "desktop-file-validate $f >/dev/null 2>&1 && ! desktop-file-validate $f 2>&1 | grep -v 'hint:' | grep -q ."
  t "Name=Atelier" "grep -qx 'Name=Atelier' $f"
  t "GenericName" "grep -qx 'GenericName=Traduction, médias et documents' $f"
  t "Categories" "grep -qx 'Categories=Utility;AudioVideo;Office;' $f"
  t "StartupWMClass=atelier" "grep -qx 'StartupWMClass=atelier' $f"
  t "Exec absolu entre guillemets" "grep -q '^Exec=\"$root/scripts/atelier-desktop\"\$' $f"
  t "2 actions presse-papiers" "grep -q 'Name=Traduire le presse-papiers' $f && grep -q \"Name=Télécharger l'URL du presse-papiers\" $f"
  t "icône installée" "[ -s $XDG_DATA_HOME/icons/hicolor/scalable/apps/atelier.svg ]"
  t "uninstall-desktop.sh" "bash scripts/uninstall-desktop.sh >/dev/null && [ ! -e $f ] && [ ! -e $XDG_DATA_HOME/icons/hicolor/scalable/apps/atelier.svg ]"
  t "uninstall idempotent" "bash scripts/uninstall-desktop.sh >/dev/null"
else
  echo "skip install: bash scripts/install-desktop.sh d'abord (venv fenêtre absent)"
fi
t "window class réel = atelier (notes PROGRESS)" "grep -q 'StartupWMClass=@WMCLASS@' desktop/atelier.desktop.in && grep -q 'NAME = \"atelier\"' scripts/atelier_desktop.py"
t "python fenêtre: syntaxe" "python3 -m py_compile scripts/atelier_desktop.py"
t "JS route/prefill: syntaxe" "node --check static/app.js && node --check static/translate.js && node --check static/youtube.js"

# --- notifications de fin de tâche
mkdir -p "$tmp/bin"
cat > "$tmp/bin/notify-send" <<'S'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$NOTIFY_LOG"
S
chmod +x "$tmp/bin/notify-send"
NOTIFY_LOG="$tmp/n.log" PATH="$tmp/bin:$PATH" py - <<'PY'
import asyncio, os
from atelier import notify
from atelier.config import cfg

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

log = os.environ["NOTIFY_LOG"]
def fire(kind="document", status="done", secs=10, params=None, **kw):
    open(log, "w").close()
    job = {"kind": kind, "title": "Tâche test", "status": status, "error": kw.get("error"), "message": kw.get("message")}
    async def go():
        notify.finished(job, params or {}, secs)
        await asyncio.sleep(0.3)
    asyncio.run(go())
    return open(log).read()

o = fire()
check("job long: notification + icône + titre", "Terminé : Tâche test" in o and "icon.svg" in o and "-a Atelier" in o)
check("job court: silencieux", fire(secs=1) == "")
o = fire(status="failed", secs=1, error="boom")
check("échec court: notifié, urgence critique", "Échec : Tâche test" in o and "critical" in o and "boom" in o)
check("dictée: silencieuse", fire(kind="dictate", secs=30) == "")
check("tts écoute: silencieux", fire(kind="tts", params={"mode": "listen"}) == "")
check("tts mp3: notifié", "Terminé" in fire(kind="tts", params={"mode": "mp3"}))
cfg["desktop"]["notify"] = False
check("toggle config: désactivé", fire() == "")
raise SystemExit(0 if ok else 1)
PY
t "notifications" "[ $? = 0 ]"
exit $fail
