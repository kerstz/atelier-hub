"""Lecteur intégré: ce que la vue peut lire telle quelle, sinon un mp4/m4a mis en cache, plus les sous-titres en VTT.
Le fichier est toujours un résultat de tâche (dossier de sortie); la lecture elle-même se fait dans la vue."""
import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import db, player, plat
from .config import cfg, data_dir, output_dir
from . import plat
from .jobs import Ctx, manager, register
from .proc import run_cmd
from .util import HEAVY

router = APIRouter()
SAFE = {  # extension -> codecs acceptés (None = pas de flux de ce type)
    ".mp4": ({"h264"}, {"aac", "mp3", "opus", "flac"}), ".m4v": ({"h264"}, {"aac", "mp3"}), ".m4a": (set(), {"aac", "alac"}),
    ".mp3": (set(), {"mp3"}), ".wav": (set(), {"pcm_s16le", "pcm_s24le", "pcm_f32le", "pcm_u8"}),
    ".ogg": (set(), {"vorbis", "opus"}), ".opus": (set(), {"opus"}), ".flac": (set(), {"flac"}),
}
CHROMIUM = {".webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}), ".mkv": ({"h264", "vp9", "av1"}, {"opus", "vorbis", "aac", "mp3", "flac"})}
MEDIA_EXT = set(SAFE) | set(CHROMIUM) | {".mov", ".avi", ".wma", ".aac", ".mka", ".ts", ".3gp"}
SUB_EXT = {".srt", ".vtt"}
_probes: dict[tuple[str, float], dict] = {}


def cache_dir() -> Path:
    d = data_dir() / "player-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_media(jid: int) -> Path:
    job = db.get(jid)
    if not job or job["status"] != "done" or not job["output"]:
        raise HTTPException(404, "pas de fichier")
    p = Path(job["output"]).resolve()
    if not p.is_file() or not p.is_relative_to(output_dir().resolve()) or p.suffix.lower() not in MEDIA_EXT:
        raise HTTPException(404, "pas de fichier audio/vidéo")
    return p


async def probe(p: Path) -> dict:
    key = (str(p), p.stat().st_mtime)
    if key in _probes:
        return _probes[key]
    proc = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p),
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **plat.spawn_kw())
    data, _ = await asyncio.wait_for(proc.communicate(), 30)
    try:
        j = json.loads(data or b"{}")
    except ValueError:
        j = {}
    st = j.get("streams", [])
    info = {
        "video": next((s["codec_name"] for s in st if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None),
        "audio": next((s["codec_name"] for s in st if s.get("codec_type") == "audio"), None),
        "subs": [{"index": n, "lang": s.get("tags", {}).get("language", ""), "title": s.get("tags", {}).get("title", "")}
                 for n, s in enumerate(x for x in st if x.get("codec_type") == "subtitle")],
        "duration": float(j.get("format", {}).get("duration") or 0),
    }
    _probes[key] = info
    return info


def native_ok(p: Path, info: dict, client: str) -> bool:
    table = dict(SAFE)
    if client == "chromium":
        table.update(CHROMIUM)
    rule = table.get(p.suffix.lower())
    if not rule:
        return False
    v, a = rule
    if info["video"] and info["video"] not in v:
        return False
    return not (info["audio"] and info["audio"] not in a) and bool(info["audio"] or info["video"])


def cache_path(p: Path, audio_only: bool) -> Path:
    h = hashlib.sha1(f"{p}:{p.stat().st_mtime_ns}".encode()).hexdigest()[:20]
    return cache_dir() / f"{h}.{'m4a' if audio_only else 'mp4'}"


async def describe(jid: int, client: str) -> dict:
    p = job_media(jid)
    info = await probe(p)
    audio_only = not info["video"]
    mode = cfg["player"]["transcode"]
    ok = mode != "always" and native_ok(p, info, client)
    cached = cache_path(p, audio_only)
    subs = [{"id": f"x{i}", "label": f"{Path(f).name}"} for i, f in enumerate(sibling_subs(p))]
    subs += [{"id": f"e{s['index']}", "label": (s["title"] or s["lang"] or f"piste {s['index'] + 1}")} for s in info["subs"]]
    return {"name": p.name, "kind": "audio" if audio_only else "video", "duration": info["duration"], "native": ok,
            "ready": ok or cached.is_file(), "needs_prepare": not ok and not cached.is_file(), "subs": subs,
            "mpv": bool(shutil.which(cfg["player"]["mpv_bin"])), "codecs": [info["video"], info["audio"]]}


def sibling_subs(p: Path) -> list[Path]:
    return sorted(f for f in p.parent.glob(glob_escape(p.stem) + "*") if f.suffix.lower() in SUB_EXT)


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def srt_to_vtt(text: str) -> str:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    if text.startswith("WEBVTT"):
        return text
    return "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)


async def prepare(ctx: Ctx, p: dict) -> None:
    src = Path(p["file"])
    info = await probe(src)
    audio_only = not info["video"]
    dest = cache_path(src, audio_only)
    if dest.is_file():
        return
    tmp = dest.with_name(dest.name + ".part.mp4" if not audio_only else dest.name + ".part.m4a")
    copy_ok = (not info["video"] or info["video"] == "h264") and (info["audio"] in (None, "aac", "mp3"))
    argv = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-progress", "pipe:1", "-i", str(src), "-map", "0:v:0?", "-map", "0:a:0?", "-sn"]
    if copy_ok and cfg["player"]["transcode"] != "always":
        argv += ["-c", "copy"]
    else:
        argv += (["-vn"] if audio_only else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]) + ["-c:a", "aac", "-b:a", "192k"]
    argv += ["-movflags", "+faststart", str(tmp)]
    dur = info["duration"] or 0

    def feed(line: str) -> None:
        if line.startswith("out_time_us=") and dur:
            try:
                ctx.set(min(0.99, int(line.split("=")[1]) / 1e6 / dur), "préparation de la lecture…")
            except ValueError:
                pass

    ctx.set(0.02, "préparation de la lecture…")
    try:
        async with HEAVY:
            await run_cmd(argv, feed)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    ctx.set(1.0, "prêt")


register("preview", prepare)


def purge_cache() -> None:
    d = data_dir() / "player-cache"
    if not d.is_dir():
        return
    now, files = time.time(), sorted((f for f in d.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime)
    for f in files:
        if now - f.stat().st_mtime > cfg["player"]["cache_days"] * 86400 or f.name.endswith(".part.mp4") or f.name.endswith(".part.m4a"):
            _rm(f)
    files = [f for f in files if f.exists()]
    total, cap = sum(f.stat().st_size for f in files), int(float(cfg["player"]["cache_max_gb"]) * (1 << 30))
    for f in files:
        if total <= cap:
            break
        total -= f.stat().st_size
        _rm(f)


def _rm(f: Path) -> None:
    try:
        f.unlink(missing_ok=True)
    except OSError:  # Windows: being streamed or still written by a preview job
        pass


def cache_bytes() -> int:
    d = data_dir() / "player-cache"
    return sum(f.stat().st_size for f in d.iterdir() if f.is_file()) if d.is_dir() else 0


def clear_cache() -> int:
    n = cache_bytes()
    shutil.rmtree(data_dir() / "player-cache", ignore_errors=True)
    return n


def _client(c: str) -> str:
    return "chromium" if c == "chromium" else "webkitgtk"


@router.get("/api/jobs/{jid}/media")
async def media_info(jid: int, client: str = "webkitgtk"):
    return await describe(jid, _client(client))


@router.get("/api/jobs/{jid}/stream")
async def media_stream(jid: int, client: str = "webkitgtk"):
    p = job_media(jid)
    d = await describe(jid, _client(client))
    if d["native"]:
        return FileResponse(p)
    c = cache_path(p, d["kind"] == "audio")
    if not c.is_file():
        raise HTTPException(409, "lecture à préparer")
    c.touch()
    return FileResponse(c, media_type="audio/mp4" if c.suffix == ".m4a" else "video/mp4")


@router.post("/api/jobs/{jid}/prepare")
async def media_prepare(jid: int, client: str = "webkitgtk"):
    p = job_media(jid)
    d = await describe(jid, _client(client))
    if d["ready"]:
        return {"ready": True}
    for j in list(manager.tasks):
        row = db.get(j)
        if row and row["kind"] == "preview" and db.params(j).get("file") == str(p):
            return {"ready": False, "job": row["id"]}
    j = manager.submit("preview", f"Préparation de la lecture : {p.name[:40]}", {"file": str(p)})
    return {"ready": False, "job": j["id"]}


@router.get("/api/jobs/{jid}/subs/{sid}.vtt")
async def media_sub(jid: int, sid: str):
    p = job_media(jid)
    if sid.startswith("x") and sid[1:].isdigit():
        subs = sibling_subs(p)
        n = int(sid[1:])
        if n >= len(subs):
            raise HTTPException(404, "sous-titre inconnu")
        return PlainTextResponse(srt_to_vtt(subs[n].read_text(encoding="utf-8", errors="replace")), media_type="text/vtt")
    if sid.startswith("e") and sid[1:].isdigit():
        proc = await asyncio.create_subprocess_exec("ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(p), "-map", f"0:s:{int(sid[1:])}",
                                                    "-f", "webvtt", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **plat.spawn_kw())
        data, _ = await asyncio.wait_for(proc.communicate(), 60)
        if proc.returncode or not data:
            raise HTTPException(404, "piste illisible")
        return PlainTextResponse(data.decode("utf-8", "replace"), media_type="text/vtt")
    raise HTTPException(404, "sous-titre inconnu")


class MpvIn(BaseModel):
    id: int
    sub: str = ""


@router.post("/api/player/mpv")
async def open_mpv(body: MpvIn):
    """Repli: lecteur externe (fenêtre séparée) pour les fichiers que la vue ne sait pas lire."""
    p = job_media(body.id)
    sub = None
    if body.sub.startswith("x") and body.sub[1:].isdigit():
        subs = sibling_subs(p)
        sub = str(subs[int(body.sub[1:])]) if int(body.sub[1:]) < len(subs) else None
    try:
        return {"player": await player.play_video(str(p), sub)}
    except RuntimeError as e:
        raise HTTPException(501, str(e))
