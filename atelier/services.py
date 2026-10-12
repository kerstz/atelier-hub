import asyncio
import os
import shlex
import subprocess
from pathlib import Path

from . import plat
from .config import cfg
from .proc import CmdError, run_cmd


def _defs() -> dict[str, dict]:
    return {k: v for k, v in cfg.get("services", {}).items() if isinstance(v, dict) and v.get("port")}


def _control(s: dict) -> str | None:
    if plat.IS_WIN:
        if s.get("winsvc"):
            return "winsvc"
        if s.get("win_exe"):
            return "winexe"
    elif s.get("unit"):
        return "systemd"
    if s.get("dir"):
        return "compose"
    return None


async def _probe(port: int) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.7)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    return True


async def status() -> list[dict]:
    defs = _defs()
    ups = await asyncio.gather(*(_probe(int(s["port"])) for s in defs.values()))
    return [
        {
            "id": k,
            "name": s.get("name", k),
            "port": int(s["port"]),
            "url": s.get("url") or f"http://127.0.0.1:{s['port']}",
            "up": up,
            "control": _control(s),
        }
        for (k, s), up in zip(defs.items(), ups)
    ]


def _win_argv(s: dict, action: str) -> list[str]:
    if s.get("winsvc"):
        return ["sc", action, s["winsvc"]]
    exe = os.path.expandvars(os.path.expanduser(s["win_exe"]))
    if action == "start":
        # posix=False keeps backslashes but also the quotes: Popen would re-quote them as literal characters
        return [exe, *(a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in shlex.split(s.get("win_args", ""), posix=False))]
    return ["taskkill", "/IM", os.path.basename(exe), "/T", "/F"]


def _argv(s: dict, action: str) -> list[str]:
    if s.get("unit"):
        return ["systemctl", "--user", action, s["unit"]]
    d = Path(s["dir"]).expanduser()
    if not d.is_dir():
        raise ValueError(f"dossier introuvable: {d}")
    base = ["docker", "compose", "--project-directory", str(d)]
    if s.get("file"):
        base += ["-f", str((d / s["file"]).expanduser())]
    # --pull never: jamais de téléchargement d'image (pas d'installation)
    return base + (["up", "-d", "--pull", "never"] if action == "start" else ["stop"])


async def act(sid: str, action: str) -> None:
    s = _defs().get(sid)
    if not s:
        raise KeyError(sid)
    if action not in ("start", "stop"):
        raise KeyError(action)
    if not _control(s):
        raise ValueError("pas de commande configurée (unit ou dir)")
    try:
        ctl = _control(s)
        if ctl == "winexe" and action == "start":  # a long-running app: detach, don't wait for it
            subprocess.Popen(_win_argv(s, action), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x00000008 | plat.CREATE_NEW_PROCESS_GROUP | plat.CREATE_NO_WINDOW if plat.NT else 0)
            return
        await asyncio.wait_for(run_cmd(_win_argv(s, action) if ctl in ("winsvc", "winexe") else _argv(s, action)), 120)
    except asyncio.TimeoutError:
        raise RuntimeError("délai dépassé (120 s)")
    except (CmdError, FileNotFoundError) as e:
        raise RuntimeError(str(e))
