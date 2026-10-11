import re
import shutil
from pathlib import Path

from . import ollama, srt, translate
from .config import cfg, data_dir, output_dir
from .jobs import Ctx, manager, register
from .subs import acquire
from .youtube import _check_url

CHARS_PER_TOKEN = 3  # conservative: timestamps and non-English text tokenize densely
RESERVE = 2400  # tokens kept for instructions + answer
HEADINGS = {"fr": ("Résumé", "Points clés", "Chapitres")}


def _secs(ts: str) -> int:
    h, m, s = ts.split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def stamp(ts: str) -> str:
    h, m, s = ts.split(",")[0].split(":")
    return f"[{int(h)}:{m}:{s}]" if int(h) else f"[{m}:{s}]"


def to_lines(cues: list[srt.Cue], span: int = 20) -> list[str]:
    """Merge cues into ~span-second lines: `[mm:ss] text`."""
    out: list[str] = []
    head, t0, parts = "", 0, []
    for c in cues:
        text = srt.flat(c.text)
        if not text:
            continue
        t = _secs(c.start)
        if parts and t - t0 >= span:
            out.append(f"{head} {' '.join(parts)}")
            parts = []
        if not parts:
            head, t0 = stamp(c.start), t
        parts.append(text)
    if parts:
        out.append(f"{head} {' '.join(parts)}")
    return out


def group(lines: list[str], limit: int) -> list[str]:
    groups, cur, size = [], [], 0
    for ln in lines:
        while len(ln) > limit:  # pathological single line
            if cur:
                groups.append("\n".join(cur))
                cur, size = [], 0
            groups.append(ln[:limit])
            ln = ln[limit:]
        if cur and size + len(ln) + 1 > limit:
            groups.append("\n".join(cur))
            cur, size = [], 0
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        groups.append("\n".join(cur))
    return groups


def notes_prompt(lang: str, i: int, n: int) -> str:
    return (
        f"Part {i} of {n} of a video transcript follows. Each line starts with its [timestamp].\n"
        f"Write concise notes in {lang}: a bullet list of the key facts, claims and topic changes. "
        "Start every bullet with the [timestamp] where it occurs, copied exactly from the input. "
        "No introduction, no conclusion, no invented facts."
    )


def final_prompt(lang: str, title: str, heads: tuple[str, str, str], notes: bool) -> str:
    what = "are the condensed notes of a video transcript" if notes else "is the transcript of a video"
    return (
        f"Below {what} titled \"{title}\". Lines are tagged with a [timestamp].\n"
        f"Write in {lang}, in Markdown, exactly these three sections:\n"
        f"## {heads[0]}\n3 to 6 sentences.\n"
        f"## {heads[1]}\n5 to 10 bullet points.\n"
        f"## {heads[2]}\nChronological list, one per line as `- [timestamp] Title`, 5 to 12 chapters, "
        "the first one at the beginning. Copy timestamps exactly from the input.\n"
        "Do not invent facts. Output only the Markdown."
    )


async def summarize(ctx: Ctx, lines: list[str], title: str, lang_code: str, lo: float, hi: float) -> str:
    model = cfg["summary"]["model"] or cfg["ollama"]["second_model"]
    num_ctx = int(cfg["summary"]["num_ctx"])
    limit = max((num_ctx - RESERVE) * CHARS_PER_TOKEN, 2000)
    lang = translate.LANGS[lang_code][0]
    heads = HEADINGS.get(lang_code, ("Summary", "Key points", "Chapters"))
    opts = {"num_ctx": num_ctx, "temperature": 0.3}

    ctx.set(lo, "attente GPU…")
    async with manager.gpu_lock:
        await ollama.exclusive(model)
        parts = group(lines, limit)
        notes = False
        rounds = 0
        while len(parts) > 1:
            rounds += 1
            if rounds > 4:
                raise RuntimeError("transcript trop long pour num_ctx")
            out = []
            for i, part in enumerate(parts, 1):
                ctx.set(lo + (hi - lo) * 0.7 * (i - 1) / len(parts), f"notes {i}/{len(parts)} (niveau {rounds})")
                msgs = [{"role": "user", "content": notes_prompt(lang, i, len(parts)) + "\n\n" + part}]
                got = await translate.complete(model, msgs, **opts)
                if not got:
                    raise RuntimeError("réponse vide du modèle")
                out.append(got)
            notes = True
            parts = group("\n".join(out).split("\n"), limit)
        ctx.set(lo + (hi - lo) * 0.75, "rédaction du résumé…")
        msgs = [{"role": "user", "content": final_prompt(lang, title, heads, notes) + "\n\n" + parts[0]}]
        text = ""
        async for tok in translate.stream_chat(model, messages=msgs, options=opts):
            text += tok
            ctx.delta(tok)
    text = text.strip()
    if not text:
        raise RuntimeError("réponse vide du modèle")
    return text


async def run(ctx: Ctx, p: dict) -> str:
    source = (p.get("source") or "").strip()
    src, lang = p.get("src", "auto"), p.get("lang") or cfg["summary"]["lang"]
    if lang not in translate.LANGS or (src != "auto" and src not in translate.LANGS):
        raise RuntimeError("langue inconnue")
    is_url = bool(re.match(r"^https?://", source))
    if is_url:
        _check_url(source)
    elif not Path(source).is_file():
        raise RuntimeError("fichier introuvable")
    work = data_dir() / "tmp" / str(ctx.id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out = output_dir("subs")
    out.mkdir(parents=True, exist_ok=True)
    uploads = (data_dir() / "uploads").resolve()
    try:
        sub, _, name, t_lo = await acquire(
            ctx, source, is_url, src, bool(p.get("force_whisper")), False, "1080", work, 0.5
        )
        cues = srt.parse(sub.read_text(encoding="utf-8", errors="replace"))
        lines = to_lines(cues)
        if not lines:
            raise RuntimeError("transcript vide")
        tag = "orig" if src == "auto" else src
        if not (not is_url and Path(source).suffix.lower() == ".srt"):
            shutil.copy(sub, out / f"{name}.{tag}.srt")  # reusable: summarize/translate again without whisper
        md = await summarize(ctx, lines, name, lang, t_lo, 0.98)
        dest = out / f"{name}.resume.md"
        dest.write_text(md + "\n", encoding="utf-8")
        ctx.set(1.0, dest.name)
        return str(dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if not is_url and Path(source).resolve().is_relative_to(uploads):
            Path(source).unlink(missing_ok=True)


register("summary", run)
