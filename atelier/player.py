"""Play a generated audio file on this machine's speakers.
Atelier only ever runs locally, and WebKitGTK's <audio> (GStreamer) aborts its web process in the native
window, so "Écouter" plays through a system player instead of the browser."""
import asyncio
import os
import shutil

from . import plat

PLAYERS = [
    ("pw-play", []), ("paplay", []), ("aplay", ["-q"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]), ("mpv", ["--no-video", "--really-quiet"]),
]
if plat.IS_WIN:
    PLAYERS = PLAYERS[3:]
if plat.IS_MAC:
    PLAYERS.insert(0, ("afplay", []))
_proc: asyncio.subprocess.Process | None = None


def available() -> str | None:
    return next((n for n, _ in PLAYERS if shutil.which(n)), None)


def playing() -> bool:
    return _proc is not None and _proc.returncode is None


async def stop() -> None:
    global _proc
    p, _proc = _proc, None
    if p and p.returncode is None:
        plat.kill_tree(p)
        try:
            await asyncio.wait_for(p.wait(), 3)
        except asyncio.TimeoutError:
            plat.kill_tree(p, force=True)


async def play(path: str) -> str:
    """Start playback (replacing any current one); returns the player name."""
    global _proc
    name = available()
    if not name:
        raise RuntimeError("aucun lecteur audio (pw-play, paplay, aplay, ffplay, mpv)")
    await stop()
    args = dict(PLAYERS)[name]
    _proc = await asyncio.create_subprocess_exec(
        shutil.which(name), *args, path,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        **plat.spawn_kw(),
    )
    return name


async def play_video(path: str, sub: str | None = None) -> str:
    """Open a video/audio file in an external mpv window (fallback when the web view can't play it)."""
    from .config import cfg
    mpv = shutil.which(os.path.expanduser(cfg["player"]["mpv_bin"]))
    if not mpv:
        raise RuntimeError("mpv introuvable (" + ("brew install mpv" if plat.IS_MAC else "winget install mpv, ou pacman -S mpv") + ")")
    global _proc
    await stop()
    argv = [mpv, "--force-window=yes", "--title=Atelier — lecture", "--really-quiet"]
    if sub:
        argv.append(f"--sub-file={sub}")
    _proc = await asyncio.create_subprocess_exec(*argv, path, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.DEVNULL, **plat.spawn_kw())
    return "mpv"
