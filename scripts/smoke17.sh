#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }

t "JS: syntaxe" "for f in static/*.js; do node --check \$f || exit 1; done"
t "JS: sélecteurs de langue des 3 onglets via langPicker" "[ \$(grep -c 'ui.langPicker(' static/translate.js static/subs.js static/docs.js | awk -F: '{s+=\$2} END{print s}') -eq 6 ]"

py - <<'PY'
import sys
from atelier import translate as T
from fastapi.testclient import TestClient
from atelier.main import app

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

orig = ["en", "fr", "es", "de", "it", "pt", "nl", "pl", "ru", "uk", "cs", "sv", "tr", "ar", "hi", "vi", "ja", "ko", "zh"]
codes = list(T.LANGS)
check("19 langues d'origine présentes, même ordre relatif", [c for c in codes if c in orig] == orig)
new = ["fil", "ceb", "pt-BR", "zh-TW", "id", "ms", "th", "he", "fa", "bn", "el", "ro", "hu", "bg", "da", "fi"]
check("16 nouvelles langues", all(c in T.LANGS for c in new) and len(codes) == 35)
check("variantes juste après leur langue (pt, pt-BR / zh, zh-TW)", codes.index("pt-BR") == codes.index("pt") + 1 and codes.index("zh-TW") == codes.index("zh") + 1)
check("noms EN/FR non vides", all(len(v) == 2 and all(v) for v in T.LANGS.values()))
check("META ne référence que des langues connues", set(T.META) <= set(T.LANGS))

# whisper / iso3 / yt-dlp
check("whisper: fil -> tl", T.whisper_code("fil") == "tl")
check("whisper: ceb (pas de modèle) -> auto", T.whisper_code("ceb") == "auto")
check("whisper: auto/fr/pt-BR/zh-TW", (T.whisper_code("auto"), T.whisper_code("fr"), T.whisper_code("pt-BR"), T.whisper_code("zh-TW")) == ("auto", "fr", "pt", "zh"))
check("iso3: fil/ceb/pt-BR/zh-TW/en", [T.iso3(c) for c in ("fil", "ceb", "pt-BR", "zh-TW", "en")] == ["fil", "ceb", "por", "zho", "eng"])
check("iso3: les 19 d'origine inchangés", [T.iso3(c) for c in orig][:3] == ["eng", "fra", "spa"] and T.iso3("zh") == "zho" and T.iso3("ar") == "ara")
check("yt-dlp: fil -> fil.*,tl.*", T.sub_langs("fil") == "fil.*,tl.*")
check("yt-dlp: he -> he.*,iw.*", T.sub_langs("he") == "he.*,iw.*")
check("yt-dlp: défaut code.*", T.sub_langs("fr") == "fr.*")
check("yt-dlp: motifs acceptés par la regex de youtube.py", all(__import__("atelier.youtube", fromlist=["x"]).LANGS_RE.match(T.sub_langs(c)) for c in codes))

# prompts
p = T.build_prompt("en", "fil", "Hello", [])
check("prompt: Filipino (fil)", "Filipino (fil)" in p and "English (en)" in p)
check("prompt: zh-TW / pt-BR", "Traditional Chinese (zh-TW)" in T.build_prompt("auto", "zh-TW", "x", []) and "Brazilian Portuguese (pt-BR)" in T.build_prompt("en", "pt-BR", "x", []))
check("prompt: ceb source", "Cebuano (ceb)" in T.build_prompt("ceb", "fr", "x", []))

# explications des variantes
L = {l["code"]: l for l in T.lang_list()}
check("auto en tête sans note", T.lang_list()[0]["code"] == "auto" and not L["auto"]["note"])
for c in ("fil", "ceb", "pt", "pt-BR", "zh", "zh-TW", "id", "ms", "ar", "he", "fa"):
    check(f"note présente: {c}", len(L[c]["note"]) > 40)
check("variantes croisées: pt <-> pt-BR", [v["code"] for v in L["pt"]["variants"]] == ["pt-BR"] and [v["code"] for v in L["pt-BR"]["variants"]] == ["pt"])
check("variantes croisées: zh <-> zh-TW", [v["code"] for v in L["zh"]["variants"]] == ["zh-TW"] and [v["code"] for v in L["zh-TW"]["variants"]] == ["zh"])
check("variantes croisées: fil <-> ceb", [v["code"] for v in L["fil"]["variants"]] == ["ceb"] and [v["code"] for v in L["ceb"]["variants"]] == ["fil"])
check("variantes croisées: id <-> ms", [v["code"] for v in L["id"]["variants"]] == ["ms"])
check("pas de variantes pour fr", L["fr"]["variants"] == [])
check("ceb: note signale dictée auto + expérimental", "détection automatique" in L["ceb"]["note"] and "expérimental" in L["ceb"]["note"])
check("fil: note explique la différence avec le tagalog", "tagalog" in L["fil"]["note"])
check("RTL signalé (ar, he, fa)", all("droite à gauche" in L[c]["note"] for c in ("ar", "he", "fa")))

with TestClient(app, base_url="http://127.0.0.1:7777") as c:
    j = c.get("/api/langs").json()
    check("API /api/langs: code, name, note, variants", all({"code", "name", "note", "variants"} <= set(x) for x in j) and len(j) == 36)
    check("API: ceb et fil présents", {"ceb", "fil"} <= {x["code"] for x in j})
raise SystemExit(0 if ok else 1)
PY
t "phase 17 (langues) hors-ligne" "[ $? = 0 ]"
exit $fail
