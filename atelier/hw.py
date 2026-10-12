"""Hardware profile: what this machine can run. Pure reads, cached; roots overridable for tests
(ATELIER_SYSFS_ROOT, ATELIER_PROC_ROOT, ATELIER_NVSMI)."""
import glob
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import cfg, data_dir

GIB = 1 << 30
VENDORS = {"0x1002": "amd", "0x10de": "nvidia", "0x8086": "intel"}
IGPU_MAX = 2 * GIB  # below this much VRAM an AMD/Intel device is an iGPU: counts as CPU


def _int(path: str) -> int | None:
    try:
        return int(Path(path).read_text().strip(), 0)
    except (OSError, ValueError):
        return None


def _gpus(sysfs: str) -> list[dict]:
    out = []
    for dev in sorted(glob.glob(f"{sysfs}/class/drm/card[0-9]*/device")):
        try:
            vendor = VENDORS.get(Path(f"{dev}/vendor").read_text().strip().lower(), "other")
        except OSError:
            continue
        total, used = _int(f"{dev}/mem_info_vram_total"), _int(f"{dev}/mem_info_vram_used")
        if total is None:
            continue
        out.append({"vendor": vendor, "card": os.path.basename(os.path.dirname(dev)), "vram_total": total,
                    "vram_free": max(total - (used or 0), 0), "igpu": total < IGPU_MAX})
    exe = os.environ.get("ATELIER_NVSMI") or shutil.which("nvidia-smi")
    if exe:
        try:
            res = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                name, total, used = [x.strip() for x in line.split(",")]
                t = int(float(total)) << 20
                out.append({"vendor": "nvidia", "card": name, "vram_total": t, "vram_free": max(t - (int(float(used)) << 20), 0), "igpu": False})
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return out


def _meminfo(proc: str) -> tuple[int, int]:
    total = avail = 0
    try:
        for line in Path(f"{proc}/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k == "MemTotal":
                total = int(v.split()[0]) * 1024
            elif k == "MemAvailable":
                avail = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return total, avail


def _flags(proc: str) -> set[str]:
    try:
        for line in Path(f"{proc}/cpuinfo").read_text().splitlines():
            if line.startswith("flags"):
                return set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return set()


def detect() -> dict:
    sysfs, proc = os.environ.get("ATELIER_SYSFS_ROOT", "/sys"), os.environ.get("ATELIER_PROC_ROOT", "/proc")
    ram_total, ram_avail = _meminfo(proc)
    flags = _flags(proc)
    gpus = _gpus(sysfs)
    real = [g for g in gpus if not g["igpu"]]
    best = max(real, key=lambda g: g["vram_total"], default=None)
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 1
    try:
        disk_free = shutil.disk_usage(data_dir() if data_dir().exists() else Path.home()).free
    except OSError:
        disk_free = 0
    return {
        "gpus": gpus, "gpu": best,
        "vram_total": best["vram_total"] if best else 0, "vram_free": best["vram_free"] if best else 0,
        "ram_total": ram_total, "ram_avail": ram_avail, "cores": cores,
        "avx2": "avx2" in flags, "avx512": "avx512f" in flags, "disk_free": disk_free,
    }


@lru_cache(maxsize=1)
def _cached() -> dict:
    return detect()


def profile(refresh: bool = False) -> dict:
    if refresh:
        _cached.cache_clear()
    return _cached()


if __name__ == "__main__":  # python -m atelier.hw [--models | --ct2 | --json]
    import json
    import sys

    from . import tiers

    p = profile()
    r = tiers.recommend(p)
    if "--models" in sys.argv:
        print("\n".join(sorted({m for m in r["models"].values() if m})))
    elif "--ct2" in sys.argv:
        print(r["ct2_model"])
    elif "--json" in sys.argv:
        print(json.dumps({"profile": p, "recommendation": r}, indent=1))
    else:
        g = p["gpu"]
        print(f"tier      : {r['tier']} — {r['label']}")
        print(f"gpu       : {g['vendor']} {g['vram_total'] / GIB:.1f} GiB" if g else "gpu       : none usable")
        print(f"ram       : {p['ram_total'] / GIB:.1f} GiB ({p['ram_avail'] / GIB:.1f} available), {p['cores']} cores, avx2={p['avx2']}")
        print(f"engine    : {r['engine']}" + (f" ({r['ct2_model']})" if r["engine"] == "ctranslate2" else ""))
        for role, m in r["models"].items():
            print(f"model     : {role:9s} {m or '-'}")
        for n in r["notes"]:
            print(f"note      : {n}")
