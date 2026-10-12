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
        if not isinstance(v, str) or not Path(v).is_absolute():
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
        try:
            p.unlink(missing_ok=True)
        except OSError:  # Windows: still open elsewhere (antivirus, viewer): left to the age purge
            pass


def missing_uploads(params: dict) -> list[Path]:
    return [p for p in upload_paths(params) if not p.is_file()]


def free_base(base: str, taken) -> str:
    """First of `base`, `base (2)`, … that `taken(candidate)` says is unused: outputs of one job share a base name."""
    for n in range(1, 1000):
        cand = base if n == 1 else f"{base} ({n})"
        if not taken(cand):
            return cand
    raise RuntimeError("trop de fichiers du même nom")


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
