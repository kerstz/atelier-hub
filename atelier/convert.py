import asyncio
import json
import os
import shutil
from pathlib import Path

from .config import cfg, data_dir, output_dir
from .jobs import Ctx, register
from .ocr import upload_name
from .proc import CmdError, run_cmd

VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".flv", ".wmv", ".3gp", ".ogv"}
AUDIO = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus", ".wma", ".mka", ".aiff", ".aif"}
AMBIGUOUS = {".mp4", ".mkv", ".webm", ".mov", ".ogg", ".3gp", ".ts", ".m4v"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp"}
TEXT = {".docx", ".doc", ".odt", ".rtf", ".txt", ".html", ".htm", ".md", ".markdown", ".rst", ".tex"}
SHEET = {".xlsx", ".xls", ".ods", ".csv"}
SLIDE = {".pptx", ".ppt", ".odp"}
EBOOK = {".epub", ".mobi", ".azw3", ".azw", ".fb2", ".kepub", ".lit"}

# target id -> (label, extension)
TARGETS = {
    "v:mp4-h264": ("MP4 · H.264 (GPU)", ".mp4"),
    "v:mp4-hevc": ("MP4 · HEVC (GPU)", ".mp4"),
    "v:mkv-h264": ("MKV · H.264 (GPU)", ".mkv"),
    "v:mkv-hevc": ("MKV · HEVC (GPU)", ".mkv"),
    "v:mkv-av1": ("MKV · AV1 (CPU, lent)", ".mkv"),
    "a:mp3": ("MP3", ".mp3"),
    "a:m4a": ("M4A (AAC)", ".m4a"),
    "a:opus": ("Opus", ".opus"),
    "a:ogg": ("OGG Vorbis", ".ogg"),
    "a:flac": ("FLAC", ".flac"),
    "a:wav": ("WAV", ".wav"),
    "i:jpg": ("JPEG", ".jpg"),
    "i:png": ("PNG", ".png"),
    "i:webp": ("WebP", ".webp"),
    "i:avif": ("AVIF", ".avif"),
    "i:heic": ("HEIC", ".heic"),
    "d:pdf": ("PDF", ".pdf"),
    "d:docx": ("DOCX", ".docx"),
    "d:odt": ("ODT", ".odt"),
    "d:rtf": ("RTF", ".rtf"),
    "d:txt": ("Texte brut", ".txt"),
    "d:html": ("HTML", ".html"),
    "d:md": ("Markdown", ".md"),
    "d:epub": ("EPUB", ".epub"),
    "d:xlsx": ("XLSX", ".xlsx"),
    "d:ods": ("ODS", ".ods"),
    "d:csv": ("CSV", ".csv"),
    "d:pptx": ("PPTX", ".pptx"),
    "d:odp": ("ODP", ".odp"),
    "e:epub": ("EPUB", ".epub"),
    "e:azw3": ("AZW3 (Kindle)", ".azw3"),
    "e:mobi": ("MOBI", ".mobi"),
    "e:fb2": ("FB2", ".fb2"),
    "e:pdf": ("PDF", ".pdf"),
    "e:docx": ("DOCX", ".docx"),
    "e:txt": ("Texte brut", ".txt"),
}
BY_CAT = {
    "video": [t for t in TARGETS if t[0] in "va"],
    "audio": [t for t in TARGETS if t[0] == "a"],
    "image": [t for t in TARGETS if t[0] == "i"],
    "text": ["d:pdf", "d:docx", "d:odt", "d:rtf", "d:txt", "d:html", "d:md", "d:epub"],
    "sheet": ["d:pdf", "d:xlsx", "d:ods", "d:csv", "d:html"],
    "slide": ["d:pdf", "d:pptx", "d:odp"],
    "ebook": [t for t in TARGETS if t[0] == "e"],
}
CATS = [("video", VIDEO), ("audio", AUDIO), ("image", IMAGE), ("text", TEXT), ("sheet", SHEET), ("slide", SLIDE), ("ebook", EBOOK)]
SAME = {".jpeg": ".jpg", ".htm": ".html", ".markdown": ".md", ".heif": ".heic", ".oga": ".ogg", ".aif": ".aiff"}

PANDOC_IN = {".md", ".markdown", ".html", ".htm", ".docx", ".odt", ".epub", ".rst", ".tex", ".rtf", ".txt"}
PANDOC_FMT = {".md": "markdown", ".markdown": "markdown", ".txt": "markdown", ".html": "html", ".htm": "html", ".docx": "docx",
              ".odt": "odt", ".epub": "epub", ".rst": "rst", ".tex": "latex", ".rtf": "rtf"}
PANDOC_OUT = {".md": "gfm", ".html": "html5", ".docx": "docx", ".odt": "odt", ".epub": "epub", ".txt": "plain"}
LO_IN = TEXT - {".md", ".markdown", ".rst", ".tex"} | SHEET | SLIDE
LO_FILTER = {".pdf": "pdf", ".docx": "docx:MS Word 2007 XML", ".odt": "odt", ".rtf": "rtf", ".txt": "txt:Text (encoded):UTF8",
             ".html": "html", ".xlsx": "xlsx", ".ods": "ods", ".csv": "csv", ".pptx": "pptx", ".odp": "odp"}
QUALITY = {"high": 0, "normal": 1, "low": 2}
# per quality tier: vaapi qp / x264 crf / x265 crf / svtav1 crf / image Q / lame -q:a
Q_VAAPI, Q_X264, Q_X265, Q_AV1, Q_IMG, Q_MP3 = (20, 25, 30), (19, 23, 28), (21, 26, 31), (24, 30, 38), (92, 82, 65), (0, 2, 5)
COMPRESSED = {".mp4", ".mkv", ".mp3", ".m4a", ".opus", ".ogg", ".flac", ".jpg", ".png", ".webp", ".avif", ".heic", ".epub", ".docx", ".odt", ".xlsx", ".pptx", ".pdf"}

_sem: asyncio.Semaphore | None = None


def ext_of(path: str | Path) -> str:
    e = Path(path).suffix.lower()
    return SAME.get(e, e)


def category(path: str | Path) -> str | None:
    e = Path(path).suffix.lower()
    return next((c for c, exts in CATS if e in exts), None)


async def probe(path: Path) -> dict:
    out: list[str] = []
    try:
        await run_cmd(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,height,disposition:format=duration",
                       "-of", "json", str(path)], out.append)
    except (CmdError, FileNotFoundError):
        return {}
    try:
        return json.loads("\n".join(out))
    except ValueError:
        return {}


def has_video(info: dict) -> bool:
    return any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in info.get("streams", []))


async def detect(path: Path) -> dict:
    cat = category(path)
    if cat in ("video", "audio") and path.suffix.lower() in AMBIGUOUS:
        info = await probe(path)
        if info.get("streams"):
            cat = "video" if has_video(info) else "audio"
    if not cat:
        return {"category": None, "targets": []}
    own = ext_of(path)
    # same extension is a no-op for documents/ebooks, a useful re-encode/resize for media
    ids = [t for t in BY_CAT[cat] if t[0] in "vai" or TARGETS[t][1] != own]
    return {"category": cat, "targets": [{"id": t, "label": TARGETS[t][0]} for t in ids]}


def catalog() -> dict:
    return {c: [{"id": t, "label": TARGETS[t][0]} for t in BY_CAT[c]] for c, _ in CATS}


def unique(out: Path, stem: str, ext: str) -> Path:
    for n in range(1, 1000):
        dest = out / (f"{stem}{ext}" if n == 1 else f"{stem} ({n}){ext}")
        try:
            os.close(os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return dest
        except FileExistsError:
            continue
    raise RuntimeError("trop de fichiers du même nom")


def need(*bins: str, hint: str) -> None:
    miss = [b for b in bins if not shutil.which(b)]
    if miss:
        raise RuntimeError(f"{miss[0]} absent: {hint}")


# ---- ffmpeg

def vaapi_ok() -> bool:
    return Path(cfg["convert"]["vaapi_device"]).exists()


def is_gpu_target(target: str) -> bool:
    return target in ("v:mp4-h264", "v:mp4-hevc", "v:mkv-h264", "v:mkv-hevc") and vaapi_ok()


async def ffmpeg(ctx: Ctx, argv: list[str], duration: float, lo: float = 0.0, hi: float = 1.0) -> None:
    errs: list[str] = []

    def feed(line: str) -> None:
        k, _, v = line.partition("=")
        if k == "out_time_us" and v.strip().isdigit() and duration > 0:
            ctx.set(lo + (hi - lo) * min(int(v) / 1e6 / duration, 0.99))
        elif not (k.isidentifier() and "=" in line):
            errs.append(line)

    try:
        await run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats", *argv], feed)
    except CmdError as e:
        raise RuntimeError(f"ffmpeg code {e.rc}: " + " | ".join(errs[-3:])) from None


def video_args(target: str, q: int, height: int, src_h: int, vaapi: bool) -> list[str]:
    _, codec = target.split(":")[1].split("-")
    scale = height and src_h and src_h > height
    if codec == "av1":
        vf = [f"scale=-2:{height}"] if scale else []
        return [*(["-vf", ",".join(vf)] if vf else []), "-c:v", "libsvtav1", "-crf", str(Q_AV1[q]), "-preset", "8", "-pix_fmt", "yuv420p"]
    if vaapi:
        vf = "format=nv12,hwupload" + (f",scale_vaapi=w=-2:h={height}" if scale else "")
        enc = "h264_vaapi" if codec == "h264" else "hevc_vaapi"
        return ["-vf", vf, "-c:v", enc, "-qp", str(Q_VAAPI[q])]
    vf = [f"scale=-2:{height}"] if scale else []
    vf.append("format=yuv420p")
    if codec == "h264":
        return ["-vf", ",".join(vf), "-c:v", "libx264", "-crf", str(Q_X264[q]), "-preset", "medium"]
    return ["-vf", ",".join(vf), "-c:v", "libx265", "-crf", str(Q_X265[q]), "-preset", "medium", "-tag:v", "hvc1"]


async def do_video(ctx: Ctx, src: Path, target: str, dest: Path, q: int, height: int) -> None:
    info = await probe(src)
    if not has_video(info):
        raise RuntimeError("aucune piste vidéo")
    dur = float(info.get("format", {}).get("duration") or 0)
    src_h = next((int(s.get("height") or 0) for s in info["streams"] if s.get("codec_type") == "video"), 0)
    mp4 = dest.suffix == ".mp4"
    mux = ["-f", "mp4" if mp4 else "matroska", str(dest)]

    async def encode(vaapi: bool, subs: bool) -> None:
        keep = subs and not mp4
        tail = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"] if mp4 else ["-c:a", "copy"]
        maps = ["-map", "0:v:0", "-map", "0:a?"] + (["-map", "0:s?", "-c:s", "copy"] if keep else [])
        dev = ["-vaapi_device", cfg["convert"]["vaapi_device"]] if vaapi else []
        await ffmpeg(ctx, [*dev, "-i", str(src), *maps, *video_args(target, q, height, src_h, vaapi), *tail, *mux], dur)

    async def attempt(vaapi: bool) -> None:
        try:
            await encode(vaapi, True)
        except RuntimeError as e:
            if "ubtitle" not in str(e):
                raise
            ctx.set(0, "sous-titres incompatibles: ignorés…")
            await encode(vaapi, False)

    if is_gpu_target(target):
        ctx.set(0, "encodage VAAPI…")
        try:
            return await attempt(True)
        except RuntimeError:
            ctx.set(0, "VAAPI échoué → CPU…")
    else:
        ctx.set(0, "encodage AV1 (CPU)…" if target.endswith("av1") else "encodage CPU…")
    await attempt(False)


AUDIO_ARGS = {
    "a:mp3": lambda q: ["-c:a", "libmp3lame", "-q:a", str(Q_MP3[q])],
    "a:m4a": lambda q: ["-c:a", "aac", "-b:a", ("256k", "192k", "128k")[q]],
    "a:opus": lambda q: ["-c:a", "libopus", "-b:a", ("160k", "128k", "96k")[q]],
    "a:ogg": lambda q: ["-c:a", "libvorbis", "-q:a", ("6", "4", "2")[q]],
    "a:flac": lambda q: ["-c:a", "flac"],
    "a:wav": lambda q: ["-c:a", "pcm_s16le"],
}


async def do_audio(ctx: Ctx, src: Path, target: str, dest: Path, q: int) -> None:
    info = await probe(src)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise RuntimeError("aucune piste audio")
    dur = float(info.get("format", {}).get("duration") or 0)
    ctx.set(0, "encodage audio…")
    await ffmpeg(ctx, ["-i", str(src), "-map", "0:a:0", "-vn", "-map_metadata", "0", *AUDIO_ARGS[target](q), str(dest)], dur)


# ---- images

IMG_OPTS = {"i:jpg": "[Q={q},optimize_coding]", "i:webp": "[Q={q}]", "i:avif": "[Q={q},effort=4]", "i:heic": "[Q={q}]", "i:png": "[compression=9]"}


async def do_image(ctx: Ctx, src: Path, target: str, dest: Path, q: int, side: int) -> None:
    need("vips", hint="sudo pacman -S libvips")
    ctx.set(0.1, "conversion image…")
    opt = IMG_OPTS[target].format(q=Q_IMG[q])
    env = {**os.environ, "VIPS_WARNING": "0"}
    if side:
        argv = ["vipsthumbnail", str(src), "-s", f"{side}x{side}>", "-o", f"{dest}{opt}"]
    else:
        argv = ["vips", "autorot", str(src), f"{dest}{opt}"]
    await run_cmd(argv, env=env)


# ---- documents

STRIP_IMAGES = Path(__file__).with_name("strip_images.lua")


async def pandoc(src: Path, dst: Path, work: Path) -> None:
    """Two steps so untrusted input can't read local files: reader runs --sandbox (no \\input, no includes,
    no image fetch) into pandoc's JSON AST; the writer (which needs its data files, so no sandbox)
    only sees the AST, with images replaced by their alt text."""
    need("pandoc", hint="sudo pacman -S pandoc-cli")
    ast = work / "ast.json"
    await run_cmd(["pandoc", "--sandbox", "-f", PANDOC_FMT[ext_of(src)], "-t", "json", "-o", str(ast), str(src)], cwd=work)
    argv = ["pandoc", "--lua-filter", str(STRIP_IMAGES), "-f", "json", "-t", PANDOC_OUT[dst.suffix], "-o", str(dst), str(ast)]
    if dst.suffix in (".html", ".md", ".txt"):
        argv[1:1] = ["--wrap=none"]
    if dst.suffix == ".html":
        argv.insert(1, "-s")
    await run_cmd(argv, cwd=work)


async def lo(src: Path, dst: Path, work: Path) -> None:
    need("soffice", hint="sudo pacman -S libreoffice-fresh")
    sub = work / "lo"
    sub.mkdir(exist_ok=True)
    flt = LO_FILTER[dst.suffix]
    argv = ["soffice", f"-env:UserInstallation=file://{work}/profile", "--headless", "--convert-to", flt, "--outdir", str(sub), str(src)]
    await run_cmd(argv)
    got = sub / f"{src.stem}{dst.suffix}"
    if not got.is_file():
        raise RuntimeError("LibreOffice: conversion échouée")
    shutil.move(got, dst)


async def do_doc(ctx: Ctx, src: Path, target: str, dest: Path, work: Path) -> None:
    se, de = ext_of(src), dest.suffix
    ctx.set(0.1, "conversion document…")
    p_in, p_out = se in PANDOC_IN, de in PANDOC_OUT
    l_in, l_out = se in LO_IN, de in LO_FILTER
    pandoc_ok = bool(shutil.which("pandoc"))
    # direct hops first; two-step chains go through a temp docx
    if p_in and p_out and (pandoc_ok or not (l_in and l_out)):
        return await pandoc(src, dest, work)
    if l_in and l_out:
        return await lo(src, dest, work)
    mid = work / "mid.docx"
    if p_in and l_out:
        await pandoc(src, mid, work)
        return await lo(mid, dest, work)
    if l_in and p_out:
        await lo(src, mid, work)
        return await pandoc(mid, dest, work)
    raise RuntimeError(f"conversion {se} → {de} non supportée")


async def do_ebook(ctx: Ctx, src: Path, target: str, dest: Path) -> None:
    need("ebook-convert", hint="sudo pacman -S calibre")
    ctx.set(0.1, "calibre…")
    await run_cmd(["ebook-convert", str(src), str(dest)], lambda l: ctx.set(message=l.strip()[:70]) if l.strip() else None,
                  env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


# ---- job

async def run(ctx: Ctx, p: dict) -> str:
    global _sem
    path = Path(p.get("path") or "")
    target = p.get("target", "")
    if not path.is_file():
        raise RuntimeError("fichier introuvable")
    if target not in TARGETS:
        raise RuntimeError("format cible inconnu")
    det = await detect(path)
    if target not in [t["id"] for t in det["targets"]]:
        raise RuntimeError(f"{path.suffix or 'ce fichier'} → {TARGETS[target][0]} non supporté")
    q = QUALITY.get(p.get("quality", "normal"), 1)
    size = max(0, min(int(p.get("size") or 0), 8192))
    if _sem is None:
        _sem = asyncio.Semaphore(max(1, int(cfg["convert"]["jobs"])))
    out = output_dir("convert")
    out.mkdir(parents=True, exist_ok=True)
    work = data_dir() / "tmp" / f"c{ctx.id}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    dest = unique(out, upload_name(path), TARGETS[target][1])
    ctx.set(0, "attente…")
    try:
        async with _sem:
            kind = target[0]
            if kind == "v":
                await do_video(ctx, path, target, dest, q, size)
            elif kind == "a":
                await do_audio(ctx, path, target, dest, q)
            elif kind == "i":
                await do_image(ctx, path, target, dest, q, size)
            elif kind == "d":
                await do_doc(ctx, path, target, dest, work)
            else:
                await do_ebook(ctx, path, target, dest)
        if not dest.stat().st_size:
            raise RuntimeError("sortie vide")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ctx.set(1.0, dest.name)
    return str(dest)


register("convert", run, gpu=lambda p: is_gpu_target(p.get("target", "")))
