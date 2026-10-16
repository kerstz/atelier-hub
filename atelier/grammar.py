import asyncio
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

import httpx

from . import plat
from .config import cfg, data_dir, ROOT
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
    """Où chercher languagetool-server.jar: notre dossier de données (scripts/get-languagetool.*), puis paquets système."""
    dirs = [data_dir() / "languagetool"]
    dirs += sorted(data_dir().glob("languagetool/LanguageTool-*"), key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)], reverse=True)  # le zip officiel s'extrait dans LanguageTool-x.y/
    if plat.NT:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                dirs += [Path(base) / "LanguageTool", Path(base) / "Programs" / "LanguageTool"]
    dirs += [Path(p) for p in ("/usr/share/languagetool", "/usr/share/java/languagetool", "/opt/languagetool", "/usr/lib/languagetool",
                               "/opt/homebrew/opt/languagetool/libexec", "/usr/local/opt/languagetool/libexec")]
    return dirs


def install_hint() -> str:
    if plat.IS_WIN:
        return "scripts/get-languagetool.sh"
    if sys.platform == "darwin":
        return "brew install languagetool"
    return "sudo pacman -S languagetool"


def command() -> list[str] | None:
    g = cfg["grammar"]
    if g["lt_cmd"]:
        return shlex.split(g["lt_cmd"], posix=not plat.NT)
    port = ["--port", str(_port())]
    if plat.IS_MAC and (b := shutil.which("languagetool-server")):  # le lanceur Homebrew règle JAVA_HOME
        return [b, *port]
    java = shutil.which("java")
    if not java:
        return None
    for d in _jar_dirs():
        if (d / "languagetool-server.jar").is_file():
            # comme le script /usr/bin/languagetool: jars listés un à un (le joker * ne charge pas les modules de langue)
            cp = [str(x) for x in (d.parent.parent / "languagetool", d, *sorted(d.glob("*.jar")), *sorted(d.glob("libs/*.jar"))) if x.exists()]
            return [java, f"-Xmx{g['lt_heap_mb']}m", "-cp", os.pathsep.join(cp), "org.languagetool.server.HTTPServer", *port]
    if (b := shutil.which("languagetool-server")):  # Homebrew & co: lanceur déjà prêt
        return [b, *port]
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
            raise CmdError("LanguageTool introuvable (et Java): " + install_hint(), 127)
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


def harper_dir(data: Path) -> Path | None:
    """Build local (scripts/build-harper.sh) ou embarqué dans static/harper (releases .exe/.deb)."""
    for d in (data / "harper", ROOT / "static" / "harper"):
        if (d / "harper.js").is_file() and (d / "harper.wasm").is_file():
            return d
    return None


def harper_built(data: Path) -> bool:
    return harper_dir(data) is not None


async def status(data: Path) -> dict:
    return {"lt_available": available(), "lt_running": await alive(), "harper": harper_built(data), "hint": plat.localize(install_hint()),
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
