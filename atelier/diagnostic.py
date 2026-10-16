import io
import json
import platform
import re
import zipfile
from collections import deque
from pathlib import Path

from . import maint, plat
from .config import VERSION, config_path, data_dir

SECRET_KEY = re.compile(r"token|key|secret|password", re.I)
ASSIGN = re.compile(r"^\s*([^=#\s]+)\s*=")
URL_USERINFO = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")
LOG_LINES = 500


def _home(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 1 else text


def clean_config(text: str) -> str:
    kept = [line for line in text.splitlines() if not (m := ASSIGN.match(line)) or not SECRET_KEY.search(m[1])]
    return _home(URL_USERINFO.sub(r"\1***@", "\n".join(kept) + "\n"))


def _log_tail() -> str | None:
    p = data_dir() / "atelier.log"
    if not p.is_file():
        return None
    with p.open(encoding="utf-8", errors="replace") as f:
        return _home("".join(deque(f, maxlen=LOG_LINES)))


def _platform() -> str:
    name = "windows" if plat.IS_WIN else "macos" if plat.IS_MAC else "linux"
    return f"{name} {platform.platform()} python {platform.python_version()}"


async def build_zip() -> bytes:
    deps = [{"id": r["id"], "label": r["label"], "present": r["ok"]} for r in await maint.deps()]
    info = {"version": VERSION, "plateforme": _platform(), "deps": deps}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostic.json", _home(json.dumps(info, ensure_ascii=False, indent=2)))
        cfg_file = config_path()
        if cfg_file.is_file():
            z.writestr("config.toml", clean_config(cfg_file.read_text(encoding="utf-8", errors="replace")))
        log = _log_tail()
        if log is not None:
            z.writestr("atelier.log", log)
    return buf.getvalue()
