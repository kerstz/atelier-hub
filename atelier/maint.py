"""System maintenance views: tool availability ("Dépendances") and disk usage / safe cleanup."""
import asyncio
import os
import shutil
from pathlib import Path

import httpx

from . import db, joblog, ollama, plat
from .config import cfg, data_dir, output_dir
from .proc import run_cmd
from .speech import DEFAULT_VOICES
from .util import binpath, upload_paths

OUT_DIRS = ("youtube", "subs", "docs", "convert", "audio", "images")


def _bin(name: str) -> str | None:
    return shutil.which(binpath(name))


WINGET = {"ffmpeg": "Gyan.FFmpeg", "yt-dlp": "yt-dlp.yt-dlp", "poppler": "oschwartz10612.Poppler",
          "pandoc-cli": "JohnMacFarlane.Pandoc", "libreoffice-fresh": "TheDocumentFoundation.LibreOffice",
          "calibre": "calibre.calibre", "tesseract": "UB-Mannheim.TesseractOCR"}


def _win_hint(hint: str) -> str:
    if hint.startswith("sudo pacman -S "):
        pkg = hint.split()[3]
        return f"winget install {WINGET[pkg]}" if pkg in WINGET else "installateur Windows: voir la page du projet"
    if hint.startswith("systemctl"):
        return "lancer Ollama (menu Démarrer)"
    return hint.replace("scripts/build-whisper.sh", "github.com/ggml-org/whisper.cpp/releases (zip Windows)")


def _row(id_: str, label: str, ok: bool, detail: str, hint: str, used: str) -> dict:
    if plat.IS_WIN:
        hint = _win_hint(hint)
    return {"id": id_, "label": label, "ok": ok, "detail": detail, "hint": "" if ok else hint, "used_by": used}


async def deps() -> list[dict]:
    c = cfg
    rows = []

    def which(id_, label, name, hint, used):
        p = _bin(name)
        rows.append(_row(id_, label, bool(p), p or "introuvable", hint, used))

    which("ffmpeg", "ffmpeg", "ffmpeg", "sudo pacman -S ffmpeg", "tout le média")
    which("ffprobe", "ffprobe", "ffprobe", "sudo pacman -S ffmpeg", "détection, conversion")
    which("yt-dlp", "yt-dlp", "yt-dlp", "sudo pacman -S yt-dlp", "YouTube, sous-titres")
    w = _bin(c["whisper"]["bin"])
    model = Path(c["whisper"]["model"]).expanduser()
    rows.append(_row("whisper", "whisper.cpp + modèle", bool(w) and model.is_file(),
                     f"{w or 'binaire absent'} · {'modèle ok' if model.is_file() else 'modèle absent'}",
                     "scripts/build-whisper.sh", "transcription, dictée"))

    # Ollama + the three configured models
    up = (await ollama.loaded())["up"]
    have: set[str] = set()
    if up:
        try:
            async with httpx.AsyncClient(timeout=3) as h:
                r = await h.get(c["ollama"]["url"].rstrip("/") + "/api/tags")
                have = {m["name"] for m in r.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            pass
    rows.append(_row("ollama", "Ollama", up, c["ollama"]["url"] if up else "injoignable", "systemctl start ollama", "traduction, résumé"))
    if up:
        from . import engines
        for role, used in (("translate", "traduction"), ("second", "résumé, 2ᵉ modèle"), ("vision", "traduction d'image")):
            m = engines.model(role)
            if not m:
                continue
            key = f"{role}_model"
            ok = m in have or (":" not in m and f"{m}:latest" in have)
            rows.append(_row(f"model-{key}", f"modèle {m}", ok, "présent" if ok else "absent", f"ollama pull {m}", used))

    which("pdf2zh", "pdf2zh-next", "pdf2zh_next", "scripts/fix-pdf2zh.sh (uv tool install pdf2zh-next)", "PDF")
    which("ocrmypdf", "ocrmypdf", c["docs"]["ocr_bin"], 'uv tool install ocrmypdf', "OCR des PDF")
    which("pdftotext", "pdftotext (poppler)", "pdftotext", "sudo pacman -S poppler", "détection de texte PDF")
    tess = _bin("tesseract")
    langs: set[str] = set()
    if tess:
        try:
            await run_cmd([tess, "--list-langs"], langs.add)
        except Exception:
            pass
    want = c["docs"]["ocr_langs"].split("+")
    miss = [x for x in want if x not in langs]
    rows.append(_row("tesseract", "tesseract + langues OCR", bool(tess) and not miss,
                     (tess or "absent") + (f" · manque {', '.join(miss)}" if tess and miss else ""),
                     "sudo pacman -S tesseract " + " ".join(f"tesseract-data-{x}" for x in miss or want), "OCR"))
    which("pandoc", "pandoc", "pandoc", "sudo pacman -S pandoc-cli", "Convertir (documents)")
    which("soffice", "LibreOffice", "soffice", "sudo pacman -S libreoffice-fresh", "documents .doc/.odt, Convertir")
    which("ebook-convert", "calibre (ebook-convert)", "ebook-convert", "sudo pacman -S calibre", "Convertir (e-books)")
    which("vips", "libvips", "vips", "sudo pacman -S libvips", "Convertir (images), ×2")

    which("piper", "Piper", c["tts"]["bin"], "uv tool install piper-tts", "Écouter, MP3")
    voices = {**DEFAULT_VOICES, **c["tts"].get("voices", {})}
    for lang, used in (("fr", "Écouter (français)"), ("en", "Écouter (anglais)")):
        voice = voices.get(lang)
        vf = Path(c["tts"]["voices_dir"]).expanduser() / f"{voice}.onnx" if voice else None
        rows.append(_row(f"voice-{lang}", f"voix {voice}", bool(vf and vf.is_file()), "présente" if vf and vf.is_file() else "absente",
                         f"uv tool run --from piper-tts python -m piper.download_voices {voice} --download-dir {c['tts']['voices_dir']}",
                         used))
    which("realesrgan", "Real-ESRGAN", c["images"]["realesrgan_bin"], "zip ncnn-vulkan: github.com/xinntao/Real-ESRGAN/releases", "Images ×2/×4")
    which("rembg", "rembg", c["images"]["rembg_bin"], 'uv tool install "rembg[cpu,cli]"', "Images (détourage)")
    which("demucs", "Demucs", c["audio"]["demucs_bin"], "uv tool install demucs", "Audio (pistes)")
    which("deep-filter", "DeepFilterNet", c["audio"]["deepfilter_bin"], "binaire deep-filter: github.com/Rikorose/DeepFilterNet/releases", "Audio (bruit)")
    if not plat.IS_WIN:
        which("notify-send", "notify-send", "notify-send", "sudo pacman -S libnotify", "notifications")
        clip = _bin("wl-paste") or _bin("xclip")
        rows.append(_row("clipboard", "wl-paste / xclip", bool(clip), clip or "introuvable", "sudo pacman -S wl-clipboard", "actions presse-papiers"))
    return rows


def _size(path: Path) -> int:
    total = 0
    if path.is_file():
        return path.stat().st_size
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _disk() -> dict:
    d = data_dir()
    base = output_dir()
    items = [{"id": f"out:{n}", "label": f"~/Atelier/{n}", "bytes": _size(base / n), "clean": False} for n in OUT_DIRS]
    items += [
        {"id": "uploads", "label": "envois en attente (uploads)", "bytes": _size(d / "uploads"), "clean": True},
        {"id": "logs", "label": "journaux des tâches", "bytes": _size(d / "logs"), "clean": True},
        {"id": "listen", "label": "lectures vocales temporaires", "bytes": _size(base / "audio" / ".listen"), "clean": True},
        {"id": "playercache", "label": "cache du lecteur (vidéos converties)", "bytes": _size(d / "player-cache"), "clean": True},
        {"id": "tmp", "label": "dossiers de travail", "bytes": _size(d / "tmp"), "clean": False},
        {"id": "db", "label": "base de données", "bytes": _size(d / "atelier.db"), "clean": False},
    ]
    u = shutil.disk_usage(d if d.exists() else Path.home())
    return {"free": u.free, "total": u.total, "items": items}


async def disk() -> dict:
    return await asyncio.to_thread(_disk)


def _clean(target: str) -> int:
    d = data_dir()
    freed = 0
    active = [p for params in db.active_params() for p in upload_paths(params)]
    if target == "uploads":
        keep = {p.resolve() for p in active}
        for f in (d / "uploads").iterdir():
            if f.is_file() and f.resolve() not in keep:
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
    elif target == "logs":
        live = {r["id"] for r in db.recent(100000) if r["status"] in ("queued", "running")}
        for f in (d / "logs").glob("*.log") if (d / "logs").is_dir() else []:
            if f.stem.isdigit() and int(f.stem) not in live:
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
    elif target == "listen":
        cache = output_dir("audio") / ".listen"
        for f in cache.iterdir() if cache.is_dir() else []:
            if f.is_file():
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
    elif target == "playercache":
        from . import media
        freed += media.clear_cache()
    else:
        raise KeyError(target)
    return freed


async def clean(target: str) -> int:
    return await asyncio.to_thread(_clean, target)


def primary_file(job: dict) -> Path | None:
    """The one file a finished job is about (for chaining into another tool), inside the output dir."""
    root = output_dir().resolve()
    out = job.get("output")
    if not out or job.get("status") != "done":
        return None
    p = Path(out)
    cand: Path | None = None
    if job["kind"] == "subtitles" and job.get("message", "").endswith(".srt"):
        cand = p / job["message"]
    elif job["kind"] == "youtube" and p.is_dir():
        media = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".flac", ".wav", ".ogg"}
        since = (job.get("started") or 0) - 2
        files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in media and f.stat().st_mtime >= since]
        cand = max(files, key=lambda f: f.stat().st_mtime, default=None)
    elif p.is_file():
        cand = p
    if cand and cand.is_file() and cand.resolve().is_relative_to(root):
        return cand.resolve()
    return None
