import base64
import json
import re
from pathlib import Path
from typing import AsyncIterator

import httpx

from . import db, engines, ollama
from .config import cfg, data_dir
from .jobs import Ctx, register

LANGS = {
    "en": ("English", "anglais"),
    "fr": ("French", "français"),
    "es": ("Spanish", "espagnol"),
    "de": ("German", "allemand"),
    "it": ("Italian", "italien"),
    "pt": ("Portuguese", "portugais (Portugal)"),
    "pt-BR": ("Brazilian Portuguese", "portugais (Brésil)"),
    "nl": ("Dutch", "néerlandais"),
    "pl": ("Polish", "polonais"),
    "ru": ("Russian", "russe"),
    "uk": ("Ukrainian", "ukrainien"),
    "cs": ("Czech", "tchèque"),
    "sv": ("Swedish", "suédois"),
    "tr": ("Turkish", "turc"),
    "ar": ("Arabic", "arabe"),
    "hi": ("Hindi", "hindi"),
    "vi": ("Vietnamese", "vietnamien"),
    "ja": ("Japanese", "japonais"),
    "ko": ("Korean", "coréen"),
    "zh": ("Chinese", "chinois simplifié"),
    "zh-TW": ("Traditional Chinese", "chinois traditionnel (Taïwan)"),
    "fil": ("Filipino", "philippin (filipino)"),
    "ceb": ("Cebuano", "cebuano (philippin des Visayas)"),
    "id": ("Indonesian", "indonésien"),
    "ms": ("Malay", "malais"),
    "th": ("Thai", "thaï"),
    "he": ("Hebrew", "hébreu"),
    "fa": ("Persian", "persan"),
    "bn": ("Bengali", "bengali"),
    "el": ("Greek", "grec"),
    "ro": ("Romanian", "roumain"),
    "hu": ("Hungarian", "hongrois"),
    "bg": ("Bulgarian", "bulgare"),
    "da": ("Danish", "danois"),
    "fi": ("Finnish", "finnois"),
}

# Per-language details other tools need; absent keys fall back to the code itself.
#   whisper: `-l` code (None = no Whisper model for it -> auto-detect)   iso3: mkv track language
#   subs: yt-dlp --sub-langs patterns   family: variants of one language shown together   note: UI explanation (fr)
_RTL = " Écriture de droite à gauche : sous-titres et texte corrects, mise en page PDF dégradée."
_EXP = " Traduction expérimentale (langue hors du cœur d'entraînement du modèle)."
META: dict[str, dict] = {
    "en": {"iso3": "eng"}, "fr": {"iso3": "fra"}, "es": {"iso3": "spa"}, "de": {"iso3": "deu"}, "it": {"iso3": "ita"},
    "nl": {"iso3": "nld"}, "pl": {"iso3": "pol"}, "ru": {"iso3": "rus"}, "uk": {"iso3": "ukr"}, "cs": {"iso3": "ces"},
    "sv": {"iso3": "swe"}, "tr": {"iso3": "tur"}, "hi": {"iso3": "hin"}, "vi": {"iso3": "vie"}, "ja": {"iso3": "jpn"},
    "ko": {"iso3": "kor"}, "th": {"iso3": "tha"}, "bn": {"iso3": "ben"}, "el": {"iso3": "ell"}, "ro": {"iso3": "ron"},
    "hu": {"iso3": "hun"}, "bg": {"iso3": "bul"}, "da": {"iso3": "dan"}, "fi": {"iso3": "fin"},
    "ar": {"iso3": "ara", "note": "Arabe standard moderne." + _RTL},
    "pt": {
        "iso3": "por", "family": "pt",
        "note": "Portugais européen (Portugal, Afrique lusophone) : « tu », « autocarro », orthographe et tournures propres. "
                "Pour le Brésil, choisir « portugais (Brésil) ».",
    },
    "pt-BR": {
        "whisper": "pt", "iso3": "por", "subs": "pt-BR.*,pt.*", "family": "pt",
        "note": "Portugais du Brésil : vocabulaire, orthographe et grammaire différents du portugais européen "
                "(« você », gérondif, « ônibus » au lieu de « autocarro »).",
    },
    "zh": {
        "iso3": "zho", "family": "zh",
        "note": "Chinois simplifié (Chine continentale, Singapour) : caractères simplifiés, mandarin standard.",
    },
    "zh-TW": {
        "whisper": "zh", "iso3": "zho", "subs": "zh-TW.*,zh-Hant.*", "family": "zh",
        "note": "Chinois traditionnel (Taïwan, Hong Kong) : caractères traditionnels et vocabulaire propre "
                "(« 軟體 » au lieu de « 软件 »). Le code zh-TW n'a pas été vérifié côté modèle de traduction.",
    },
    "fil": {
        "whisper": "tl", "iso3": "fil", "subs": "fil.*,tl.*", "family": "ph",
        "note": "Langue nationale des Philippines, standardisée à partir du tagalog (région de Manille) avec de nombreux "
                "emprunts à l'anglais. Comprise presque partout dans le pays : choix par défaut. "
                "Dictée et transcription via le modèle tagalog.",
    },
    "ceb": {
        "whisper": None, "iso3": "ceb", "subs": "ceb.*", "family": "ph",
        "note": "Langue des Visayas et de Mindanao (Cebu, Davao), distincte du filipino/tagalog et non intelligible avec lui."
                + _EXP + " Pas de modèle Whisper cebuano : dictée et transcription en détection automatique.",
    },
    "id": {
        "iso3": "ind", "family": "ms",
        "note": "Langue nationale d'Indonésie. Très proche du malais (intelligibles à l'écrit) mais vocabulaire et usages différents.",
    },
    "ms": {
        "iso3": "msa", "family": "ms",
        "note": "Malaisie, Brunéi, Singapour. Très proche de l'indonésien (intelligibles à l'écrit) mais orthographe, "
                "emprunts et usages différents." + _EXP,
    },
    "he": {"iso3": "heb", "subs": "he.*,iw.*", "note": "Hébreu moderne." + _RTL},
    "fa": {"iso3": "fas", "note": "Persan (farsi)." + _RTL},
}


NOTES_EN = {
    "ar": "Modern Standard Arabic. Right-to-left script: subtitles and text are fine, PDF layout is degraded.",
    "pt": "European Portuguese (Portugal, lusophone Africa): \"tu\", \"autocarro\", own spelling and phrasing. "
          "For Brazil, pick \"Portuguese (Brazil)\".",
    "pt-BR": "Brazilian Portuguese: vocabulary, spelling and grammar differ from European Portuguese "
             "(\"você\", gerund, \"ônibus\" instead of \"autocarro\").",
    "zh": "Simplified Chinese (mainland China, Singapore): simplified characters, standard Mandarin.",
    "zh-TW": "Traditional Chinese (Taiwan, Hong Kong): traditional characters and own vocabulary "
             "(\"軟體\" instead of \"软件\"). The zh-TW code has not been verified on the translation model side.",
    "fil": "National language of the Philippines, standardized from Tagalog (Manila region) with many English "
           "loanwords. Understood almost everywhere in the country: default choice. Dictation and transcription "
           "use the Tagalog model.",
    "ceb": "Language of the Visayas and Mindanao (Cebu, Davao), distinct from Filipino/Tagalog and not mutually "
           "intelligible with it. Experimental translation. No Whisper model for Cebuano: dictation and "
           "transcription use automatic detection.",
    "id": "National language of Indonesia. Very close to Malay (mutually intelligible in writing) but with "
          "different vocabulary and usage.",
    "ms": "Malaysia, Brunei, Singapore. Very close to Indonesian (mutually intelligible in writing) but with "
          "different spelling, loanwords and usage. Experimental translation.",
    "he": "Modern Hebrew. Right-to-left script: subtitles and text are fine, PDF layout is degraded.",
    "fa": "Persian (Farsi). Right-to-left script: subtitles and text are fine, PDF layout is degraded.",
}


def _meta(code: str) -> dict:
    return META.get(code, {})


def whisper_code(code: str) -> str:
    """`-l` value for whisper.cpp: the language, or "auto" when Whisper has no model for it."""
    if code == "auto":
        return "auto"
    return _meta(code).get("whisper", code) or "auto"


def iso3(code: str) -> str:
    return _meta(code).get("iso3", "und")


def sub_langs(code: str) -> str:
    return _meta(code).get("subs", f"{code}.*")


def lang_list() -> list[dict]:
    fam: dict[str, list[str]] = {}
    for c in LANGS:
        if f := _meta(c).get("family"):
            fam.setdefault(f, []).append(c)
    out = [{"code": "auto", "name": "Détecter", "name_en": "Detect", "note": "", "note_en": "", "variants": []}]
    for c, n in LANGS.items():
        m = _meta(c)
        same = [x for x in fam.get(m.get("family", ""), []) if x != c]
        out.append({
            "code": c, "name": n[1], "name_en": n[0], "note": m.get("note", ""), "note_en": NOTES_EN.get(c, ""),
            "variants": [{"code": x, "name": LANGS[x][1], "name_en": LANGS[x][0]} for x in same],
        })
    return out


def parse_glossary(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            a, b = (x.strip() for x in line.split("=", 1))
            if a and b:
                pairs.append((a, b))
    return pairs


def build_prompt(src: str, tgt: str, text: str, glossary: list[tuple[str, str]]) -> str:
    t_name = LANGS[tgt][0]
    if src == "auto":
        head = (
            f"You are a professional translator. Your goal is to accurately convey the meaning and nuances "
            f"of the original text while adhering to {t_name} ({tgt}) grammar, vocabulary, and cultural sensitivities.\n"
            f"Produce only the {t_name} translation, without any additional explanations or commentary. "
            f"Please translate the following text into {t_name}:"
        )
    else:
        s_name = LANGS[src][0]
        head = (
            f"You are a professional {s_name} ({src}) to {t_name} ({tgt}) translator. Your goal is to accurately "
            f"convey the meaning and nuances of the original {s_name} text while adhering to {t_name} grammar, "
            f"vocabulary, and cultural sensitivities.\n"
            f"Produce only the {t_name} translation, without any additional explanations or commentary. "
            f"Please translate the following {s_name} text into {t_name}:"
        )
    low = text.lower()
    used = [(a, b) for a, b in glossary if a.lower() in low]
    if used:
        head += "\nUse these fixed translations for the following terms:\n" + "\n".join(f"{a} = {b}" for a, b in used)
    return f"{head}\n\n\n{text}"


def chunk(text: str, limit: int) -> list[str]:
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if len(para) <= limit:
            if para:
                units.append(para)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", para):
            while len(sent) > limit:
                if cur:
                    units.append(cur)
                    cur = ""
                units.append(sent[:limit])
                sent = sent[limit:]
            if cur and len(cur) + len(sent) + 1 > limit:
                units.append(cur)
                cur = sent
            else:
                cur = f"{cur} {sent}".strip()
        if cur:
            units.append(cur)
    chunks: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + len(u) + 2 > limit:
            chunks.append(cur)
            cur = u
        else:
            cur = f"{cur}\n\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


async def stream_chat(
    model: str, prompt: str | None = None, *, messages: list[dict] | None = None, options: dict | None = None
) -> AsyncIterator[str]:
    url = cfg["ollama"]["url"].rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": messages or [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"temperature": 0, **(options or {})},
    }
    try:
        wait = float(cfg["ollama"]["timeout"])
        async with httpx.AsyncClient(timeout=httpx.Timeout(wait, connect=5)) as c:
            async with c.stream("POST", url, json=body) as r:
                if r.status_code == 404:
                    raise RuntimeError(f"modèle introuvable: {model} (ollama pull {model})")
                if r.status_code != 200:
                    raise RuntimeError(f"ollama {r.status_code}: {(await r.aread())[:200]!r}")
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    if text := d.get("message", {}).get("content"):
                        yield text
                    if d.get("done"):
                        return
    except httpx.ConnectError:
        raise RuntimeError("Ollama injoignable")
    except httpx.ReadTimeout:
        raise RuntimeError(f"Ollama ne répond plus (aucun retour depuis {wait:.0f} s)")


async def complete(model: str, messages: list[dict], **options) -> str:
    return "".join([t async for t in stream_chat(model, messages=messages, options=options)]).strip()


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE = 20 << 20


def image_prompt(src: str, tgt: str, glossary: list[tuple[str, str]]) -> str:
    t_name = LANGS[tgt][0]
    s = f" The text is in {LANGS[src][0]}." if src != "auto" else ""
    head = (
        f"Read all the text visible in this image and translate it into {t_name} ({tgt}).{s} "
        "Keep the reading order and the line and paragraph breaks. "
        f"Output only the {t_name} translation, with no description of the image and no commentary. "
        "If the image contains no text, output exactly: [no text]"
    )
    if glossary:
        head += "\nUse these fixed translations for the following terms:\n" + "\n".join(f"{a} = {b}" for a, b in glossary)
    return head


async def run_image(ctx: Ctx, p: dict, src: str, tgt: str) -> None:
    path = Path(p["image"]).resolve()
    if not path.is_relative_to((data_dir() / "uploads").resolve()) or not path.is_file():
        raise RuntimeError("image introuvable")
    if path.suffix.lower() not in IMAGE_EXT:
        raise RuntimeError("image: png, jpg ou webp")
    if path.stat().st_size > MAX_IMAGE:
        raise RuntimeError("image trop lourde (> 20 Mo)")
    b64 = base64.b64encode(path.read_bytes()).decode()
    name = re.sub(r"^[0-9a-f]{8}-", "", path.name)
    model = engines.model("vision")
    if not model:
        raise RuntimeError("traduction d'image indisponible sur ce matériel (aucun modèle vision recommandé)")
    ctx.set(0.05, "libération de la VRAM…")
    await ollama.exclusive(model)
    ctx.set(0.15, f"lecture de l'image ({model})…")
    prompt = image_prompt(src, tgt, parse_glossary(p.get("glossary") or ""))
    msgs = [{"role": "user", "content": prompt, "images": [b64]}]
    out = ""
    async for tok in stream_chat(model, messages=msgs):
        out += tok
        ctx.delta(tok)
    if not out.strip():
        raise RuntimeError("réponse vide du modèle")
    db.add_translation(src, tgt, f"[image] {name}", out.strip())


async def run(ctx: Ctx, p: dict) -> None:
    if p.get("image"):
        src, tgt = p.get("src", "auto"), p.get("tgt", "fr")
        if tgt not in LANGS or (src != "auto" and src not in LANGS):
            raise RuntimeError("langue inconnue")
        return await run_image(ctx, p, src, tgt)
    text, src, tgt = (p.get("text") or "").strip(), p.get("src", "auto"), p.get("tgt", "fr")
    if not text:
        raise RuntimeError("texte vide")
    if tgt not in LANGS or (src != "auto" and src not in LANGS):
        raise RuntimeError("langue inconnue")
    glossary = parse_glossary(p.get("glossary") or "")
    chunks = chunk(text, int(cfg["translate"]["chunk_chars"]))
    model = engines.model("translate")
    eng = await engines.pick()
    parts = []
    prev: list[dict] = []  # previous block + its translation: keeps terms and register consistent across blocks
    for i, c in enumerate(chunks):
        ctx.set(i / len(chunks), f"bloc {i + 1}/{len(chunks)}")
        if i:
            ctx.delta("\n\n")
        if eng.name == "ctranslate2":  # NLLB: one segment at a time, no prompt, no streaming
            out = (await eng.translate_items([(1, c)], src, tgt))[1]
            ctx.delta(out)
            parts.append(out.strip())
            continue
        prompt = build_prompt(src, tgt, c, glossary)
        out = ""
        async for tok in stream_chat(model, messages=prev + [{"role": "user", "content": prompt}]):
            out += tok
            ctx.delta(tok)
        parts.append(out.strip())
        if cfg["translate"].get("context", True):
            prev = [{"role": "user", "content": prompt}, {"role": "assistant", "content": out.strip()}]
    db.add_translation(src, tgt, text, "\n\n".join(parts))


register("translate", run, gpu=True)
