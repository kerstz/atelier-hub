import base64
import json
import re
from pathlib import Path
from typing import AsyncIterator

import httpx

from . import db, ollama
from .config import cfg, data_dir
from .jobs import Ctx, register

LANGS = {
    "en": ("English", "anglais"),
    "fr": ("French", "français"),
    "es": ("Spanish", "espagnol"),
    "de": ("German", "allemand"),
    "it": ("Italian", "italien"),
    "pt": ("Portuguese", "portugais"),
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
    "zh": ("Chinese", "chinois"),
}


def lang_list() -> list[dict]:
    return [{"code": "auto", "name": "Détecter"}] + [{"code": c, "name": n[1]} for c, n in LANGS.items()]


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
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5)) as c:
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
    try:
        if path.suffix.lower() not in IMAGE_EXT:
            raise RuntimeError("image: png, jpg ou webp")
        if path.stat().st_size > MAX_IMAGE:
            raise RuntimeError("image trop lourde (> 20 Mo)")
        b64 = base64.b64encode(path.read_bytes()).decode()
        name = re.sub(r"^[0-9a-f]{8}-", "", path.name)
    finally:
        path.unlink(missing_ok=True)
    model = cfg["ollama"]["vision_model"]
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
    model = cfg["ollama"]["translate_model"]
    parts = []
    for i, c in enumerate(chunks):
        ctx.set(i / len(chunks), f"bloc {i + 1}/{len(chunks)}")
        if i:
            ctx.delta("\n\n")
        out = ""
        async for tok in stream_chat(model, build_prompt(src, tgt, c, glossary)):
            out += tok
            ctx.delta(tok)
        parts.append(out.strip())
    db.add_translation(src, tgt, text, "\n\n".join(parts))


register("translate", run, gpu=True)
