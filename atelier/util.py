import asyncio
import shutil
from pathlib import Path

from .config import data_dir

# one CPU-heavy ML job at a time (demucs, rembg, deepfilter)
HEAVY = asyncio.Semaphore(1)


def consume(path: Path) -> None:
    if path.resolve().is_relative_to((data_dir() / "uploads").resolve()):
        path.unlink(missing_ok=True)


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
