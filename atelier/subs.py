import asyncio
import re
import shutil
from pathlib import Path

from . import ollama, srt, translate
from .batch import Translator, numbered
from .config import cfg, data_dir, output_dir
from .jobs import Ctx, manager, register
from .proc import run_cmd
from .youtube import PCT_RE, QUALITIES, _check_url, _mode_args, _net_args

PROG_RE = re.compile(r"progress\s*=\s*(\d+)%")
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma"}
SKIP_EXT = {".srt", ".vtt", ".part", ".ytdl", ".json", ".webp", ".jpg", ".png"}
ISO3 = {
    "en": "eng", "fr": "fra", "es": "spa", "de": "deu", "it": "ita", "pt": "por", "nl": "nld",
    "pl": "pol", "ru": "rus", "uk": "ukr", "cs": "ces", "sv": "swe", "tr": "tur", "ar": "ara",
    "hi": "hin", "vi": "vie", "ja": "jpn", "ko": "kor", "zh": "zho",
}


async def translate_cues(ctx: Ctx, cues: list[srt.Cue], src: str, tgt: str, glossary, lo: float, hi: float) -> list[str]:
    tr = Translator(src, tgt, glossary)
    items = [(i + 1, srt.flat(c.text)) for i, c in enumerate(cues)]
    results = dict(items)
    todo = [it for it in items if re.search(r"\w", it[1])]
    size = int(cfg["subtitles"]["batch"])
    batches = [todo[i : i + size] for i in range(0, len(todo), size)]
    prev: list[dict] = []
    ctx.set(lo, "attente GPU…")
    async with manager.gpu_lock:
        for bi, batch in enumerate(batches):
            res = await tr.batch(batch, prev)
            results.update(res)
            prev = [
                {"role": "user", "content": tr.prompt(numbered(batch))},
                {"role": "assistant", "content": numbered([(n, res[n]) for n, _ in batch])},
            ]
            ctx.set(lo + (hi - lo) * (bi + 1) / len(batches), f"traduction {bi + 1}/{len(batches)}")
    return [results[n] for n, _ in items]


def _dl_progress(ctx: Ctx, lo: float, hi: float, streams: int, label: str):
    state = {"n": 0}

    def feed(line: str) -> None:
        if line.startswith("[download] Destination:"):
            state["n"] += 1
        elif m := PCT_RE.match(line):
            frac = (max(state["n"], 1) - 1 + float(m[1]) / 100) / streams
            ctx.set(lo + (hi - lo) * min(frac, 1), f"{label} {m[1]} %")

    return feed


def _ytdlp(work: Path, url: str, *args: str) -> list[str]:
    return [
        "yt-dlp", "--newline", "--no-playlist", "--windows-filenames", "--no-mtime",
        "-P", str(work), "-o", "%(title).120B.%(ext)s", *_net_args(), *args, "--", url,
    ]


async def fetch_url(ctx, url, src, force_whisper, want_video, quality, work, hi):
    found = None
    if not force_whisper:
        ctx.set(0, "sous-titres existants…")
        pat = ("en" if src == "auto" else src) + ".*"
        flags = ["--write-subs"] + (["--write-auto-subs"] if cfg["subtitles"]["use_auto_captions"] else [])
        await run_cmd(_ytdlp(work, url, "--skip-download", *flags, "--sub-langs", pat, "--convert-subs", "srt"))
        files = sorted(work.glob("*.srt"))
        found = next((f for f in files if f.name.endswith(f".{src}.srt")), files[0] if files else None)
    media = None
    if found is None or want_video:
        if want_video:
            args, streams = _mode_args("video", quality, "")
        else:
            args, streams = ["-f", "bestaudio/best"], 1
        await run_cmd(
            _ytdlp(work, url, *args), _dl_progress(ctx, 0.0, hi, streams, "téléchargement")
        )
        media = next((f for f in sorted(work.iterdir()) if f.suffix.lower() not in SKIP_EXT), None)
        if media is None:
            raise RuntimeError("téléchargement: aucun média")
    return found, media


async def transcribe(ctx: Ctx, media: Path, lang: str, work: Path, lo: float, hi: float) -> Path:
    bin_, model = cfg["whisper"]["bin"], Path(cfg["whisper"]["model"]).expanduser()
    if not shutil.which(bin_) or not model.is_file():
        raise RuntimeError("whisper.cpp absent: scripts/build-whisper.sh")
    wav = work / "audio.wav"
    ctx.set(lo, "extraction audio…")
    await run_cmd(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(media), "-vn", "-ar", "16000",
         "-ac", "1", "-c:a", "pcm_s16le", str(wav)]
    )

    def feed(line: str) -> None:
        if m := PROG_RE.search(line):
            ctx.set(lo + (hi - lo) * int(m[1]) / 100, f"transcription {m[1]} %")

    ctx.set(lo, "attente GPU…")
    async with manager.gpu_lock:
        if cfg["gpu"]["free_vram"]:
            await ollama.unload_all()
        await run_cmd(
            [bin_, "-m", str(model), "-f", str(wav), "-l", lang, "-osrt", "-of", str(work / "whisper"),
             "-pp", "-t", str(cfg["whisper"]["threads"])],
            feed,
        )
    return work / "whisper.srt"


async def mux(video: Path, sub: Path, dest: Path, lang: str) -> None:
    probe = await run_cmd(
        ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)]
    )
    n = len([x for x in probe if x.strip()])
    await run_cmd(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(video), "-i", str(sub),
         "-map", "0", "-map", "1:0", "-c", "copy",
         f"-metadata:s:s:{n}", f"language={ISO3.get(lang, 'und')}",
         f"-metadata:s:s:{n}", f"title={translate.LANGS[lang][1].capitalize() if lang in translate.LANGS else 'Original'}",
         f"-disposition:s:{n}", "default", str(dest)]
    )


def _clean(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    return name[:120] or "sous-titres"


async def acquire(ctx, source, is_url, src, force_whisper, want_video, quality, work, whisper_hi):
    """Transcript SRT for a URL / local media / local SRT. Returns (srt, media|None, name, progress_after)."""
    sub: Path | None = None
    media: Path | None = None
    uploads = (data_dir() / "uploads").resolve()
    if is_url:
        sub, media = await fetch_url(ctx, source, src, force_whisper, want_video, quality, work, 0.1)
    else:
        local = Path(source)
        name = re.sub(r"^[0-9a-f]{8}-", "", local.name) if local.resolve().is_relative_to(uploads) else local.name
        if local.suffix.lower() == ".srt":
            sub = local
        else:
            media = local
    if sub is not None:
        stem = sub.stem
        if is_url and "." in stem:
            stem = stem.rsplit(".", 1)[0]
        name_base = stem if is_url else Path(name).stem
    else:
        name_base = media.stem if is_url else Path(name).stem
    t_lo = 0.1
    if sub is None:
        sub = await transcribe(ctx, media, "auto" if src == "auto" else src, work, 0.1, whisper_hi)
        t_lo = whisper_hi
    return sub, media, _clean(name_base), t_lo


async def run(ctx: Ctx, p: dict) -> str:
    source = (p.get("source") or "").strip()
    src, tgt = p.get("src", "en"), p.get("tgt", "fr")
    if tgt not in translate.LANGS or (src != "auto" and src not in translate.LANGS):
        raise RuntimeError("langue inconnue")
    do_tr, want_mux = p.get("translate", True) and src != tgt, bool(p.get("mux"))
    is_url = bool(re.match(r"^https?://", source))
    if is_url:
        _check_url(source)
    elif not Path(source).is_file():
        raise RuntimeError("fichier introuvable")
    if str(p.get("quality", "1080")) not in QUALITIES:
        raise RuntimeError("qualité invalide")
    glossary = translate.parse_glossary(p.get("glossary") or "")

    work = data_dir() / "tmp" / str(ctx.id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out = output_dir("subs")
    out.mkdir(parents=True, exist_ok=True)
    try:
        sub, media, name_base, t_lo = await acquire(
            ctx, source, is_url, src, bool(p.get("force_whisper")), want_mux,
            str(p.get("quality", "1080")), work, 0.5 if do_tr else 0.95,
        )
        cues = srt.parse(sub.read_text(encoding="utf-8", errors="replace"))
        if not cues:
            raise RuntimeError("aucune réplique dans le SRT")
        src_tag = "orig" if src == "auto" else src
        shutil.copy(sub, out / f"{name_base}.{src_tag}.srt")
        final = out / f"{name_base}.{src_tag}.srt"
        if do_tr:
            texts = await translate_cues(ctx, cues, src, tgt, glossary, t_lo, 0.95)
            final = out / f"{name_base}.{tgt}.srt"
            final.write_text(srt.build(cues, texts), encoding="utf-8")
        if want_mux and media is not None and media.suffix.lower() not in AUDIO_EXT:
            ctx.set(0.95, "incrustation mkv…")
            await mux(media, final, out / f"{name_base}.{tgt if do_tr else src_tag}.mkv", tgt if do_tr else src)
        ctx.set(1.0, final.name)
        return str(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


register("subtitles", run)
