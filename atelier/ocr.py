import re
import shutil
from pathlib import Path

from .config import cfg, data_dir, output_dir
from .jobs import Ctx, register
from .proc import run_cmd

MIN_CHARS = 50


def upload_name(path: Path) -> str:
    uploads = (data_dir() / "uploads").resolve()
    name = re.sub(r"^[0-9a-f]{8}-", "", path.name) if path.resolve().is_relative_to(uploads) else path.name
    return re.sub(r'[\\/:*?"<>|]+', "_", Path(name).stem).strip(" .")[:120] or "document"


async def has_text(pdf: Path) -> bool:
    """Text layer present in the first pages? Unknown (no pdftotext) counts as yes."""
    if not shutil.which("pdftotext"):
        return True
    n = 0

    def feed(line: str) -> None:
        nonlocal n
        n += sum(c.isalnum() for c in line)

    await run_cmd(["pdftotext", "-l", "5", str(pdf), "-"], feed)
    return n >= MIN_CHARS


async def _check(bin_: str, langs: str) -> None:
    if not shutil.which(bin_):
        raise RuntimeError(f"{bin_} absent: uv tool install ocrmypdf")
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract absent: sudo pacman -S tesseract")
    have: set[str] = set()
    await run_cmd(["tesseract", "--list-langs"], have.add)
    miss = [l for l in langs.split("+") if l not in have]
    if miss:
        raise RuntimeError("données tesseract manquantes: sudo pacman -S " + " ".join(f"tesseract-data-{l}" for l in miss))


async def ocr_pdf(ctx: Ctx, src: Path, dst: Path, force: bool = False) -> None:
    d = cfg["docs"]
    await _check(d["ocr_bin"], d["ocr_langs"])
    ctx.set(message="OCR…")
    await run_cmd(
        [d["ocr_bin"], "-f" if force else "-s", "-r", "-l", d["ocr_langs"], "-j", str(d["ocr_jobs"]),
         "-O", "0", "--output-type", "pdf", str(src), str(dst)],
        lambda line: ctx.set(message=line.strip()[:70]) if line.strip() else None,
    )


async def run(ctx: Ctx, p: dict) -> str:
    path = Path(p.get("path") or "")
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise RuntimeError("PDF introuvable")
    out = output_dir("docs")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{upload_name(path)}.ocr.pdf"
    try:
        await ocr_pdf(ctx, path, dest, bool(p.get("force")))
    finally:
        if path.resolve().is_relative_to((data_dir() / "uploads").resolve()):
            path.unlink(missing_ok=True)
    ctx.set(1.0, dest.name)
    return str(out)


register("ocr", run)
