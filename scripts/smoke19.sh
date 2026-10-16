#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# ---------------- installer (dry-run only: nothing is installed)
t "install.sh: syntaxe" "bash -n install.sh"
t "install.sh: --help" "./install.sh --help | grep -q 'tier=minimal'"
t "install.sh: option inconnue -> 64" "./install.sh --nope >/dev/null 2>&1; [ \$? = 64 ]"
osr() { printf 'ID=%s\nID_LIKE="%s"\n' "$1" "$2" > "$tmp/os-$1"; echo "$tmp/os-$1"; }
plan() { ATELIER_OS_RELEASE=$(osr "$1" "$2") ./install.sh --dry-run --yes "${@:3}" 2>&1; }
t "arch/cachyos -> pacman" "plan cachyos 'arch' | grep -q 'sudo pacman -S --needed --noconfirm' && plan cachyos arch | grep -q 'family: arch'"
t "arch: paquets standard (tesseract-data-fra, pandoc-cli, libreoffice-fresh)" "plan arch '' | grep -q 'tesseract-data-fra.*pandoc-cli.*libreoffice-fresh'"
t "ubuntu (ID_LIKE=debian) -> apt" "plan ubuntu debian | grep -q 'apt-get install -y' && plan ubuntu debian | grep -q 'apt-get update'"
t "debian: poppler-utils, tesseract-ocr-fra, libvips-tools, gir1.2-webkit2-4.1" "plan debian '' | grep -q 'poppler-utils' && plan debian '' | grep -q 'tesseract-ocr-fra' && plan debian '' | grep -q 'libvips-tools' && plan debian '' | grep -q 'gir1.2-webkit2-4.1'"
t "mint (ID_LIKE=ubuntu debian) -> debian" "plan linuxmint 'ubuntu debian' | grep -q 'family: debian'"
t "fedora -> dnf" "plan fedora '' | grep -q 'dnf install -y' && plan fedora '' | grep -q 'tesseract-langpack-fra'"
t "nobara (ID_LIKE=fedora) -> dnf" "plan nobara 'rhel fedora' | grep -q 'family: fedora'"
t "opensuse-tumbleweed -> zypper" "plan opensuse-tumbleweed 'opensuse suse' | grep -q 'zypper --non-interactive install'"
t "distro inconnue: pas de paquets système, avertissement, outils Python quand même" "plan gentoo '' > $tmp/u.txt; grep -q 'Unrecognized distro' $tmp/u.txt && ! grep -q 'System packages' $tmp/u.txt && grep -q 'uv tool install yt-dlp' $tmp/u.txt"
t "minimal: pas d'OCR/whisper/desktop" "plan cachyos arch --tier=minimal > $tmp/m.txt; ! grep -q 'tesseract' $tmp/m.txt && ! grep -q 'build-whisper' $tmp/m.txt && ! grep -q 'install-desktop' $tmp/m.txt && grep -q 'install-service' $tmp/m.txt"
t "full: calibre, piper-tts, rembg, demucs, realesrgan, deep-filter" "plan cachyos arch --tier=full > $tmp/f.txt; for k in calibre 'uv tool install piper-tts' 'rembg[cpu,cli]' 'uv tool install demucs' Real-ESRGAN deep-filter; do grep -qF -- \"\$k\" $tmp/f.txt || exit 1; done"
t "--no-whisper / --no-desktop / --no-service respectés" "plan cachyos arch --no-whisper --no-desktop --no-service > $tmp/n.txt; ! grep -q 'build-whisper' $tmp/n.txt && ! grep -q 'install-desktop' $tmp/n.txt && ! grep -q 'install-service' $tmp/n.txt"
t "--ollama (arch) -> ollama-vulkan + enable" "plan cachyos arch --ollama > $tmp/o.txt; grep -Eq 'ollama-(vulkan|cuda)' $tmp/o.txt && grep -Eq 'systemctl enable --now ollama|already installed' $tmp/o.txt"
t "--ollama (debian) -> installateur officiel, jamais lancé sans confirmation" "plan debian '' --ollama | grep -q 'ollama.com/install.sh'"
t "--models -> modèles recommandés pour la machine (atelier.hw)" "plan cachyos arch --models > $tmp/p.txt; grep -q 'recommended for this machine' $tmp/p.txt && grep -q 'atelier.hw --models' $tmp/p.txt"
t "uv non-Arch: installateur officiel proposé (confirmation)" "PATH=/usr/bin:/bin plan debian '' | grep -qE 'astral.sh/uv/install.sh|uv tool install'"
t "dry-run n'exécute rien (sudo factice qui échoue)" "mkdir -p $tmp/bin; printf '#!/bin/sh\nexit 99\n' > $tmp/bin/sudo; chmod +x $tmp/bin/sudo; PATH=$tmp/bin:\$PATH plan cachyos arch >/dev/null"

# ---------------- i18n (node: translate() sur le vrai code)
cat > "$tmp/i18n_test.js" <<'JS'
const fs = require("fs"), vm = require("vm");
const ctx = {localStorage: {getItem: () => "en", setItem() {}}, navigator: {language: "fr-FR"}, document: {}, location: {}, console};
vm.createContext(ctx);
for (const f of ["static/i18n.en.js", "static/i18n.js"]) vm.runInContext(fs.readFileSync(f, "utf8"), ctx);
const T = vm.runInContext("i18n", ctx);
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
console.log(JSON.stringify(input.map((s) => T.t(s))));
JS
python3 - "$tmp" <<'PY'
import json, re, sys
from html.parser import HTMLParser
out = []
class P(HTMLParser):
    skip = 0
    def handle_starttag(s, tag, attrs):
        if tag in ("script", "style"): s.skip += 1
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label") and v: out.append(v.strip())
    def handle_endtag(s, tag):
        if tag in ("script", "style"): s.skip -= 1
    def handle_data(s, d):
        t = " ".join(d.split())
        if t and not s.skip: out.append(t)
P().feed(open("static/index.html").read())
json.dump(sorted(set(x for x in out if re.search(r"[A-Za-zÀ-ÿ]{2}", x))), open(sys.argv[1] + "/html.json", "w"), ensure_ascii=False)
PY
t "i18n: node exécute translate()" "node $tmp/i18n_test.js $tmp/html.json > $tmp/html_en.json"
python3 - "$tmp" <<'PY'
import json, sys
d = sys.argv[1]
fr = json.load(open(d + "/html.json")); en = json.load(open(d + "/html_en.json"))
SAME = {"Atelier", "Navigation", "YouTube", "Audio", "Images", "Services", "Format", "Action", "Option", "Source", "PDF", "OCR", "MP3",
        "Ctrl ↵", "https://www.youtube.com/watch?v=…", "English", "Langue / Language", "Documents", "Mode", "Photo", "Anime", "Test GPU (5 s)", "Test CPU (5 s)", "Diagnostic"}
left = [f for f, e in zip(fr, en) if f == e and f not in SAME]
open(d + "/left.txt", "w").write("\n".join(left))
print(f"{len(fr)} chaînes statiques, {len(left)} sans traduction")
for x in left: print("   manque:", x)
PY
t "i18n: toutes les chaînes statiques du HTML ont une traduction" "[ ! -s $tmp/left.txt ]"
cat > "$tmp/samples.json" <<'JS'
["Échec : fichier introuvable", "traduction 3/10", "attente GPU…", "Document : rapport.pdf", "3 tâche(s) lancée(s).", "Terminé : foo",
 "Ollama ne répond plus (aucun retour depuis 300 s)", "modèle introuvable: gemma3:12b (ollama pull gemma3:12b)", "utile pour : tout le média",
 "— présent", "Vidéo · 3 fichiers", "interrompu", "phrase totalement inconnue du dictionnaire"]
JS
node "$tmp/i18n_test.js" "$tmp/samples.json" > "$tmp/samples_en.json"
t "i18n: messages dynamiques du backend" "python3 -c \"
import json; o = json.load(open('$tmp/samples_en.json'))
exp = ['Failed: file not found', 'translating 3/10', 'waiting for GPU…', 'Document: rapport.pdf', '3 task(s) started.', 'Done: foo',
       'Ollama is not responding (no data for 300 s)', 'model not found: gemma3:12b (ollama pull gemma3:12b)', 'needed for: all media',
       '— present', 'Video · 3 files', 'interrupted', 'phrase totalement inconnue du dictionnaire']
bad = [(a, b) for a, b in zip(o, exp) if a != b]
print(bad) if bad else None
raise SystemExit(1 if bad else 0)\""
t "i18n: français inchangé par défaut (lang=fr, aucune écriture)" "grep -q 'if (lang === \"fr\") return;' static/i18n.js"
t "i18n: scripts chargés avant ui.js" "[ \$(grep -n 'i18n.js' static/index.html | head -1 | cut -d: -f1) -lt \$(grep -n 'src=\"ui.js\"' static/index.html | cut -d: -f1) ]"
t "i18n: API langues: name_en/note_en" "PYTHONPATH=. uv run --frozen --offline python -c \"
from atelier import translate as T
L = {l['code']: l for l in T.lang_list()}
assert L['fil']['name_en'] == 'Filipino' and 'Tagalog' in L['fil']['note_en'] and L['pt']['variants'][0]['name_en'] == 'Brazilian Portuguese'
assert all(L[c]['note_en'] for c in L if L[c]['note'])\""
t "README: EN + FR, liens croisés, installation via install.sh" "grep -q 'README.fr.md' README.md && grep -q 'README.md' README.fr.md && grep -q 'install.sh' README.md && grep -q 'install.sh' README.fr.md"
exit $fail
