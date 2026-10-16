import glob
import os
import time

import httpx

from . import plat
from .config import cfg


def _read(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _device() -> str | None:
    want = cfg["gpu"]["card"]
    if want != "auto":
        return f"/sys/class/drm/{want}/device"
    best, size = None, -1
    for p in glob.glob("/sys/class/drm/card[0-9]*/device"):
        total = _read(f"{p}/mem_info_vram_total")
        if total is not None and total > size:
            best, size = p, total
    return best


def _win_vram() -> dict | None:
    cards = plat.win_gpus()
    want = cfg["gpu"]["card"]
    if want != "auto":
        cards = [c for c in cards if want.lower() in c["card"].lower()] or cards
    if not cards:
        return None
    c = max(cards, key=lambda g: g["total"])
    return {"card": c["card"], "used": c["used"], "total": c["total"], "busy": None}


_mac_used: list[float] = [0.0, 0.0]  # (monotonic time, bytes): /api/system polls every few seconds


def _mac_vram() -> dict | None:
    g = plat.mac_gpu()
    if not g:
        return None
    if time.monotonic() - _mac_used[0] < 5:
        return {"card": g["card"], "used": int(_mac_used[1]), "total": g["vram_total"], "busy": None}
    used = 0
    try:  # unified memory: what Ollama holds is the only GPU use we can attribute
        r = httpx.get(cfg["ollama"]["url"].rstrip("/") + "/api/ps", timeout=1)
        used = sum(int(m.get("size_vram") or 0) for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        pass
    _mac_used[:] = [time.monotonic(), min(used, g["vram_total"])]
    return {"card": g["card"], "used": int(_mac_used[1]), "total": g["vram_total"], "busy": None}


def vram() -> dict | None:
    if plat.IS_WIN:
        return _win_vram()
    if plat.IS_MAC:
        return _mac_vram()
    dev = _device()
    if not dev:
        return None
    total, used = _read(f"{dev}/mem_info_vram_total"), _read(f"{dev}/mem_info_vram_used")
    if total is None or used is None:
        return None
    return {
        "card": os.path.basename(os.path.dirname(dev)),
        "used": used,
        "total": total,
        "busy": _read(f"{dev}/gpu_busy_percent"),
    }
