import asyncio
import json
import os
import re

from .config import cfg, output_dir
from . import plat
from .jobs import Ctx, register
from .proc import CmdError, run_cmd

QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "360"}
LANGS_RE = re.compile(r"^[A-Za-z0-9,._*-]{1,60}$")
ITEM_RE = re.compile(r"Downloading (?:item|video) (\d+) of (\d+)")
DEST_RE = re.compile(r"^\[download\] Destination: (.+)$")
PATH_RES = [
    re.compile(r'^\[Merger\] Merging formats into "(.+)"$'),
    re.compile(r"^\[ExtractAudio\] Destination: (.+)$"),
    re.compile(r"^\[download\] (.+) has already been downloaded$"),
]
PCT_RE = re.compile(r"^\[download\]\s+([\d.]+)%")
SPEED_RE = re.compile(r"at\s+(\S+/s)")
ETA_RE = re.compile(r"ETA\s+(\S+)")


def _net_args() -> list[str]:
    y = cfg["youtube"]
    a = []
    if y.get("cookies_from_browser"):
        a += ["--cookies-from-browser", y["cookies_from_browser"]]
    if y.get("rate_limit"):
        a += ["--limit-rate", y["rate_limit"]]
    return a


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://\S+$", url):
        raise RuntimeError("URL invalide")
    return url


async def probe(url: str) -> dict:
    url = _check_url(url)
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "-J", "--encoding", "utf-8", "--flat-playlist", "--no-warnings", *_net_args(), "--", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **plat.spawn_kw(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 90)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        lines = err.decode(errors="replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"yt-dlp code {proc.returncode}")
    d = json.loads(out)
    pl = d.get("_type") == "playlist"
    return {
        "title": d.get("title"),
        "playlist": pl,
        "count": len(d.get("entries") or []) if pl else 1,
        "uploader": d.get("uploader") or d.get("channel"),
    }


def _mode_args(mode: str, quality: str, sub_langs: str) -> tuple[list[str], int]:
    if mode == "video":
        fmt = "bv*+ba/b" if quality == "best" else f"bv*[height<={quality}]+ba/b[height<={quality}]/bv*+ba/b"
        return ["-f", fmt, "--merge-output-format", "mkv", "--embed-metadata", "--embed-chapters"], 2
    if mode == "audio":
        return [
            "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg",
        ], 1
    if mode == "subs":
        if not LANGS_RE.match(sub_langs):
            raise RuntimeError("langues invalides")
        return ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs, "--convert-subs", "srt"], 1
    raise RuntimeError(f"mode inconnu: {mode}")


class Tracker:
    def __init__(self, ctx: Ctx, streams: int):
        self.ctx, self.streams = ctx, streams
        self.item, self.total, self.stream = 1, 1, 0
        self.path = ""
        self.errors = 0
        self.frac = 0.0

    def feed(self, line: str) -> None:
        if line.startswith("ERROR:"):
            self.errors += 1
        if m := ITEM_RE.search(line):
            self.item, self.total, self.stream = int(m[1]), int(m[2]), 0
            return
        if m := DEST_RE.match(line):
            self.stream += 1
            self.path = m[1]
            return
        for r in PATH_RES:
            if m := r.match(line):
                self.path = m[1]
                return
        if m := PCT_RE.match(line):
            frac = (max(self.stream, 1) - 1 + float(m[1]) / 100) / self.streams
            overall = (self.item - 1 + min(frac, 0.99)) / self.total
            self.frac = max(self.frac, overall)
            parts = [f"{self.item}/{self.total}"] if self.total > 1 else []
            parts += [os.path.basename(self.path)[:50], f"{m[1]} %"]
            if s := SPEED_RE.search(line):
                parts.append(s[1])
            if e := ETA_RE.search(line):
                parts.append(f"ETA {e[1]}")
            self.ctx.set(self.frac, " · ".join(p for p in parts if p))


async def run(ctx: Ctx, p: dict) -> str:
    url = _check_url(p.get("url"))
    mode, quality = p.get("mode", "video"), str(p.get("quality", "best"))
    if quality not in QUALITIES:
        raise RuntimeError("qualité invalide")
    mode_args, streams = _mode_args(mode, quality, p.get("sub_langs") or cfg["youtube"]["sub_langs"])

    is_playlist = False
    if p.get("playlist"):
        ctx.set(0, "analyse…")
        is_playlist = (await probe(url))["playlist"]
    template = (
        "%(playlist_title).80B/%(playlist_index)02d - %(title).120B.%(ext)s"
        if is_playlist
        else "%(title).120B.%(ext)s"
    )
    out = output_dir("youtube")
    out.mkdir(parents=True, exist_ok=True)
    argv = [
        "yt-dlp", "--newline", "--encoding", "utf-8", "--windows-filenames", "--no-mtime", "--trim-filenames", "150",
        "--yes-playlist" if is_playlist else "--no-playlist",
        "-P", str(out), "-o", template,
        *_net_args(), *mode_args, "--", url,
    ]
    tr = Tracker(ctx, streams)
    try:
        await run_cmd(argv, tr.feed)
    except CmdError as e:
        if not (e.rc == 1 and tr.path and tr.errors):
            raise
        ctx.set(message=f"terminé avec {tr.errors} erreur(s)")
    return os.path.dirname(tr.path) if tr.path else str(out)


register("youtube", run)
