import asyncio
import os
import shutil
from pathlib import Path

from .config import data_dir

# one CPU-heavy ML job at a time (demucs, rembg, deepfilter)
HEAVY = asyncio.Semaphore(1)


UPLOAD_KEYS = ("path", "image", "source")


def upload_paths(params: dict) -> list[Path]:
    """Input files of a job that live inside the uploads dir (resolved: no `..` or symlink escape)."""
    root = (data_dir() / "uploads").resolve()
    out = []
    for k in UPLOAD_KEYS:
        v = params.get(k)
        if not isinstance(v, str) or not v.startswith("/"):
            continue
        p = Path(v).resolve()
        if p.is_relative_to(root) and p != root:
            out.append(p)
    return out


def consume_uploads(params: dict, still_used: set[Path] | None = None) -> None:
    """Delete a finished job's uploaded inputs, except files another queued/running job still reads.
    Only called on success so failed/cancelled jobs can be retried."""
    for p in upload_paths(params):
        if still_used and p in still_used:
            continue
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
