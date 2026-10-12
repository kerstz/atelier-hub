import re
import shutil
import time
from pathlib import Path

from . import translate
from .config import cfg, output_dir
from .convert import need, unique
from .jobs import Ctx, register
from .proc import run_cmd
from .util import binpath, consume, src_file, workdir

DEFAULT_VOICES = {
    "fr": "fr_FR-siwis-medium", "en": "en_US-lessac-medium", "de": "de_DE-thorsten-medium",
    "es": "es_ES-davefx-medium", "it": "it_IT-paola-medium",
}
MAX_CHARS = 30000
BLANK_RE = re.compile(r"\[(BLANK_AUDIO|MUSIC|SILENCE)\]", re.I)


def voice_for(lang: str) -> Path:
    t = cfg["tts"]
    name = {**DEFAULT_VOICES, **t.get("voices", {})}.get(lang)
    if not name:
        raise RuntimeError(f"pas de voix pour '{lang}': ajouter [tts.voices] {lang} = \"…\" dans config.toml")
    onnx = Path(t["voices_dir"]).expanduser() / f"{name}.onnx"
    if not onnx.is_file():
        raise RuntimeError(
            f"voix {name} absente: uv tool run --from piper-tts python -m piper.download_voices {name} "
            f"--download-dir {Path(t['voices_dir']).expanduser()}"
        )
    return onnx


async def tts(ctx: Ctx, p: dict) -> str:
    text = (p.get("text") or "").strip()
    lang = p.get("lang", "fr")
    if not text:
        raise RuntimeError("texte vide")
    if lang not in translate.LANGS:
        raise RuntimeError("langue inconnue")
    bin_ = binpath(cfg["tts"]["bin"])
    need(bin_, hint="uv tool install piper-tts")
    onnx = voice_for(lang)
    work = workdir(ctx.id, "t")
    try:
        (work / "in.txt").write_text(text[:MAX_CHARS], encoding="utf-8")
        wav = work / "out.wav"
        ctx.set(0.1, "synthèse vocale…")
        with open(work / "in.txt", "rb") as f:
            await run_cmd([bin_, "-m", str(onnx), "-f", str(wav)], stdin=f)
        if not wav.is_file() or wav.stat().st_size < 100:
            raise RuntimeError("piper: aucune sortie")
        out = output_dir("audio")
        if p.get("mode") == "mp3":
            out.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^\w\- ]+", "", (p.get("title") or text)[:40]).strip() or "lecture"
            dest = unique(out, f"{stem}.{lang}", ".mp3")
            ctx.set(0.8, "encodage mp3…")
            await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-q:a", "2", str(dest)])
        else:
            cache = out / ".listen"
            cache.mkdir(parents=True, exist_ok=True)
            dest = cache / f"{ctx.id}.wav"
            shutil.move(wav, dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ctx.set(1.0, dest.name)
    return str(dest)


def purge_listen(max_age: float = 86400) -> None:
    cache = output_dir("audio") / ".listen"
    if cache.is_dir():
        for f in cache.iterdir():
            if f.is_file() and time.time() - f.stat().st_mtime > max_age:
                f.unlink(missing_ok=True)


async def dictate(ctx: Ctx, p: dict) -> None:
    path = src_file(p)
    lang = p.get("lang", "auto")
    if lang != "auto" and lang not in translate.LANGS:
        raise RuntimeError("langue inconnue")
    bin_, model = cfg["whisper"]["bin"], Path(cfg["whisper"]["model"]).expanduser()
    if not shutil.which(bin_) or not model.is_file():
        raise RuntimeError("whisper.cpp absent: scripts/build-whisper.sh")
    work = workdir(ctx.id, "d")
    try:
        wav = work / "mic.wav"
        ctx.set(0.1, "préparation audio…")
        await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ar", "16000",
                       "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        ctx.set(0.3, "transcription…")
        await run_cmd([bin_, "-m", str(model), "-f", str(wav), "-l", lang, "-nt", "-otxt", "-of", str(work / "t"),
                       "-t", str(cfg["whisper"]["threads"])])
        txt = (work / "t.txt").read_text(encoding="utf-8", errors="replace") if (work / "t.txt").is_file() else ""
    finally:
        shutil.rmtree(work, ignore_errors=True)
        consume(path)
    text = " ".join(BLANK_RE.sub(" ", txt).split())
    if not text:
        raise RuntimeError("aucune parole détectée")
    ctx.delta(text)
    ctx.set(1.0, text[:60])


register("tts", tts)
register("dictate", dictate, gpu=True)
