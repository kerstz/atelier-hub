import asyncio
import os
import shutil
from pathlib import Path

from .config import data_dir

# one CPU-heavy ML job at a time (demucs, rembg, deepfilter)
HEAVY = asyncio.Semaphore(1)


def upload_paths(params: dict) -> list[Path]:
    """Params values (str, or list of str) that point inside the uploads dir."""
    root = str((data_dir() / "uploads").resolve()) + os.sep
    vals: list = []
    for v in params.values():
        vals += v if isinstance(v, list) else [v]
    return [Path(v) for v in vals if isinstance(v, str) and v.startswith(root)]


def consume_uploads(params: dict) -> None:
    """Delete a finished job's uploaded inputs. Only called on success so failed/cancelled jobs can be retried."""
    for p in upload_paths(params):
        p.unlink(missing_ok=True)


def missing_uploads(params: dict) -> list[Path]:
    return [p for p in upload_paths(params) if not p.is_file()]


def workdir(ctx_id: int, tag: str) -> Path:
    work = data_dir() / "tmp" / f"{tag}{ctx_id}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    return work


def src_file(p: dict) -> Path:
    path = Path(p.get("path") or "")
    if not path.is_file():
        raise RuntimeError("fichier introuvable")
    return path


def binpath(name: str) -> str:
    """Config binary: expand ~ when it is a path, else leave to PATH lookup."""
    return os.path.expanduser(name) if name.startswith("~") else name
