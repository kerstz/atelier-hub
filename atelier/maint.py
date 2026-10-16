"""System maintenance views: tool availability ("Dépendances") and disk usage / safe cleanup."""
import asyncio
import functools
import os
import shutil
from pathlib import Path

import httpx

from . import db, grammar, joblog, ollama, plat
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
    return plat.localize(hint)


# hints are written for Arch (pacman); Debian/Ubuntu and Fedora get their own package manager and names
PKG = {
    "debian": ("sudo apt install", "tesseract-ocr-{}", {"poppler": "poppler-utils", "tesseract": "tesseract-ocr", "pandoc-cli": "pandoc",
                                                       "libreoffice-fresh": "libreoffice", "libvips": "libvips-tools",
                                                       "libnotify": "libnotify-bin"}),
    "fedora": ("sudo dnf install", "tesseract-langpack-{}", {"ffmpeg": "ffmpeg-free", "poppler": "poppler-utils", "pandoc-cli": "pandoc",
                                                            "libreoffice-fresh": "libreoffice", "libvips": "vips-tools"}),
}
FAMILIES = {"arch": "arch cachyos manjaro endeavouros garuda artix arcolinux",
            "debian": "debian ubuntu linuxmint pop raspbian zorin elementary neon kali",
            "fedora": "fedora rhel centos rocky almalinux nobara bazzite ultramarine"}


@functools.cache
def distro_family(path: str = "/etc/os-release") -> str:
    """arch | debian | fedora | unknown, from os-release ID then ID_LIKE (same table as install.sh)."""
    try:
        kv = dict(line.partition("=")[::2] for line in Path(path).read_text().splitlines())
    except OSError:
        return "unknown"
    for w in (kv.get("ID", "") + " " + kv.get("ID_LIKE", "")).replace('"', "").replace("'", "").split():
        for fam, ids in FAMILIES.items():
            if w in ids.split():
                return fam
    return "unknown"


def _linux_hint(hint: str, fam: str) -> str:
    if not hint.startswith("sudo pacman -S ") or fam not in PKG:
        return hint
    if fam == "debian" and hint == "sudo pacman -S yt-dlp":  # apt's yt-dlp lags behind YouTube changes
        return "sudo apt install pipx && pipx install yt-dlp"
    cmd, tess, names = PKG[fam]
    pkgs = [tess.format(p[15:]) if p.startswith("tesseract-data-") else names.get(p, p) for p in hint.split()[3:]]
    return f"{cmd} {' '.join(pkgs)}"


def _row(id_: str, label: str, ok: bool, detail: str, hint: str, used: str) -> dict:
    if plat.IS_WIN:
        hint = _win_hint(hint)
    else:
        hint = plat.localize(hint)  # pacman -> this distro's package manager; .deb: scripts/ -> /opt/atelier/scripts
    return {"id": id_, "label": label, "ok": ok, "detail": detail, "hint": "" if ok else hint, "used_by": used,
            "essential": id_ in ESSENTIAL}


# what a first launch needs (Traduire, YouTube, Convertir); everything else is optional and shown folded
ESSENTIAL = {"ffmpeg", "ffprobe", "yt-dlp", "ollama", "model-translate_model"}


def setup_info(rows: list[dict]) -> dict:
    """First-launch assistant: what is missing among the essentials and the one command that installs it."""
    miss = [r for r in rows if r["essential"] and not r["ok"]]
    if any(r["id"] == "ffmpeg" for r in miss):  # same package: one line is enough
        miss = [r for r in miss if r["id"] != "ffprobe"]
    d = plat.distro()
    cmds: list[str] = []
    if d == "windows":
        if any(r["id"] != "model-translate_model" for r in miss):
            cmds.append(plat.localize("scripts/win-setup.sh") + " -Tier minimal -Models")
        elif miss:
            cmds.append(miss[0]["hint"])
    else:
        pk = [p for r in miss for p in (("ffmpeg",) if r["id"] in ("ffmpeg", "ffprobe") else ("yt-dlp",) if r["id"] == "yt-dlp" else ())]
        pk = list(dict.fromkeys(pk))
        if d == "debian" and "yt-dlp" in pk:  # apt's yt-dlp lags behind YouTube: pipx (same choice as _linux_hint)
            cmds.append(f"sudo apt install {'ffmpeg ' if 'ffmpeg' in pk else ''}pipx && pipx install yt-dlp")
        elif pk:
            cmds.append(_linux_hint("sudo pacman -S " + " ".join(pk), d))
        cmds += [r["hint"] for r in miss if r["id"] in ("ollama", "model-translate_model")]
    if d != "windows" and any(r["id"] == "ollama" for r in miss):  # model row exists once Ollama answers; win-setup -Models pulls it
        from . import engines
        if m := engines.model("translate"):
            cmds.append(f"ollama pull {m}")
    return {"os": d, "missing": miss, "commands": cmds, "can_run": plat.NT and plat.FROZEN and bool(miss),
            "output": str(output_dir()), "win_setup": plat.localize("scripts/win-setup.sh") if d == "windows" else ""}


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
    vert = (data_dir() / "vert" / "index.html").is_file()
    rows.append(_row("vert", "VERT (conversion navigateur)", vert, "construit" if vert else "non construit",
                     "scripts/build-vert.sh", "Convertir › Navigateur (optionnel)"))
    rows.append(_row("languagetool", "LanguageTool (correcteur FR)", grammar.available(),
                     "trouvé" if grammar.available() else "introuvable", grammar.install_hint(), "Correcteur › français"))
    hp = grammar.harper_built(data_dir())
    rows.append(_row("harper", "Harper (correcteur EN)", hp, "construit" if hp else "non construit",
                     "scripts/build-harper.sh", "Correcteur › anglais (optionnel)"))
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
    rows.append(_row("ollama", "Ollama", up, c["ollama"]["url"] if up else "injoignable", plat.ollama_hint(), "traduction, résumé"))
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
    items = [{"id": f"out:{n}", "label": str(base / n), "bytes": _size(base / n), "clean": False} for n in OUT_DIRS]
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


def _rm(f: Path) -> int:
    """Bytes freed; 0 for a file still open (Windows refuses to delete it: upload in progress, file being played)."""
    try:
        n = f.stat().st_size
        f.unlink(missing_ok=True)
        return n
    except OSError:
        return 0


def _clean(target: str) -> int:
    d = data_dir()
    freed = 0
    active = [p for params in db.active_params() for p in upload_paths(params)]
    if target == "uploads":
        keep = {p.resolve() for p in active}
        for f in (d / "uploads").iterdir():
            if f.is_file() and f.resolve() not in keep:
                freed += _rm(f)
    elif target == "logs":
        live = {r["id"] for r in db.recent(100000) if r["status"] in ("queued", "running")}
        for f in (d / "logs").glob("*.log") if (d / "logs").is_dir() else []:
            if f.stem.isdigit() and int(f.stem) not in live:
                freed += _rm(f)
    elif target == "listen":
        cache = output_dir("audio") / ".listen"
        for f in cache.iterdir() if cache.is_dir() else []:
            if f.is_file():
                freed += _rm(f)
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
