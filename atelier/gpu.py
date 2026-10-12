import glob
import os

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


def vram() -> dict | None:
    if plat.IS_WIN:
        return _win_vram()
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
