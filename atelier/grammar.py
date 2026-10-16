import asyncio
import shlex
import shutil
import time
from pathlib import Path

import httpx

from . import plat
from .config import cfg
from .proc import CmdError

LANGS = {"fr": "fr", "en": "en-US", "en-gb": "en-GB", "es": "es", "de": "de-DE", "pt": "pt-PT", "it": "it"}
MAX_CHARS = 60000
_proc: asyncio.subprocess.Process | None = None
_lock = asyncio.Lock()
_last = 0.0
_reaper: asyncio.Task | None = None


def _port() -> int:
    return int(cfg["grammar"]["lt_port"])


def _url(path: str) -> str:
    return f"http://127.0.0.1:{_port()}{path}"


def _jar_dirs() -> list[Path]:
    return [Path(p) for p in ("/usr/share/languagetool", "/usr/share/java/languagetool", "/opt/languagetool", "/usr/lib/languagetool")]


def command() -> list[str] | None:
    g = cfg["grammar"]
    if g["lt_cmd"]:
        return shlex.split(g["lt_cmd"], posix=not plat.NT)
    port = ["--port", str(_port())]
    if (b := shutil.which("languagetool-server")):
        return [b, *port]
    java = shutil.which("java")
    for d in _jar_dirs():
        if java and (d / "languagetool-server.jar").is_file():
            return [java, f"-Xmx{g['lt_heap_mb']}m", "-cp", str(d / "*"), "org.languagetool.server.HTTPServer", *port]
    return None


def available() -> bool:
    return command() is not None


async def alive() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            return (await c.get(_url("/v2/languages"))).status_code == 200
    except httpx.HTTPError:
        return False


async def _idle_stop() -> None:
    global _proc
    while _proc and _proc.returncode is None:
        await asyncio.sleep(30)
        if time.monotonic() - _last > cfg["grammar"]["lt_idle_min"] * 60:
            await stop()


async def start() -> None:
    global _proc, _reaper
    async with _lock:
        if await alive():
            return
        cmd = command()
        if not cmd:
            raise CmdError("LanguageTool introuvable: sudo pacman -S languagetool", 127)
        if _proc and _proc.returncode is None:
            plat.kill_tree(_proc, True)
        try:  # écoute sur 127.0.0.1 seulement (sans --public)
            _proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **plat.spawn_kw())
        except OSError as e:
            raise CmdError(plat.missing_tool(e), 127)
        for _ in range(120):
            if _proc.returncode is not None:
                raise CmdError("LanguageTool s'est arrêté au démarrage", _proc.returncode)
            if await alive():
                break
            await asyncio.sleep(0.5)
        else:
            await stop()
            raise CmdError("LanguageTool ne répond pas (60 s)", 1)
        if not _reaper or _reaper.done():
            _reaper = asyncio.create_task(_idle_stop())


async def stop() -> None:
    global _proc
    p, _proc = _proc, None
    if p and p.returncode is None:
        plat.kill_tree(p, False)
        try:
            await asyncio.wait_for(p.wait(), 5)
        except asyncio.TimeoutError:
            plat.kill_tree(p, True)


def harper_built(data: Path) -> bool:
    return (data / "harper" / "harper.js").is_file() and (data / "harper" / "harper.wasm").is_file()


async def status(data: Path) -> dict:
    return {"lt_available": available(), "lt_running": await alive(), "harper": harper_built(data),
            "dialect": cfg["grammar"]["en_dialect"], "langs": list(LANGS)}


async def check(text: str, lang: str) -> list[dict]:
    global _last
    code = LANGS.get(lang)
    if not code:
        raise ValueError("langue non gérée")
    if len(text) > MAX_CHARS:
        raise ValueError(f"texte trop long (max {MAX_CHARS} caractères)")
    await start()
    _last = time.monotonic()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(_url("/v2/check"), data={"text": text, "language": code, "level": "default"})
        r.raise_for_status()
    _last = time.monotonic()
    out = []
    for m in r.json().get("matches", []):
        rule = m.get("rule", {})
        out.append({
            "offset": m["offset"], "length": m["length"],
            "message": m.get("message", ""), "short": m.get("shortMessage", ""),
            "kind": rule.get("category", {}).get("name", ""), "rule": rule.get("id", ""),
            "replacements": [x["value"] for x in m.get("replacements", [])[:8]],
        })
    return out
