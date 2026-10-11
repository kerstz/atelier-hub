import glob
import os

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


def vram() -> dict | None:
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
