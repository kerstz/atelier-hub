import csv
import os
import re
import shutil
from pathlib import Path

from . import inline, ocr, translate
from .batch import Translator, numbered
from .config import cfg, data_dir, output_dir
from .jobs import Ctx, manager, register
from .office import LOADERS
from .proc import run_cmd
from .srt import flat

PAGES_RE = re.compile(r"^[0-9,\- ]{1,60}$")
CONVERT = {".doc": "docx", ".odt": "docx", ".rtf": "docx", ".ppt": "pptx", ".odp": "pptx", ".xls": "xlsx", ".ods": "xlsx"}
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
BAR_RE = re.compile(r"^\s*(.+?)\s+[━╸╺╾╼─\-]*\s*(\d+)/(\d+)\s+\d+:\d\d:\d\d")


async def translate_texts(ctx: Ctx, texts: list[str], src, tgt, glossary, lo: float, hi: float) -> dict[str, str]:
    uniq = list(dict.fromkeys(texts))
    items = list(enumerate(uniq, 1))
    limit = int(cfg["translate"]["chunk_chars"])
    batches: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    size = 0
    for it in items:
        if cur and (size + len(it[1]) > limit or len(cur) >= 40):
            batches.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += len(it[1])
    if cur:
        batches.append(cur)
    tr, res, prev = Translator(src, tgt, glossary), {}, []
    ctx.set(lo, "attente GPU…")
    async with manager.gpu_lock:
        for bi, b in enumerate(batches):
            got = await tr.batch(b, prev)
            res.update(got)
            prev = [
                {"role": "user", "content": tr.prompt(numbered(b))},
                {"role": "assistant", "content": numbered([(n, got[n]) for n, _ in b])},
            ]
            ctx.set(lo + (hi - lo) * (bi + 1) / len(batches), f"traduction {bi + 1}/{len(batches)}")
    return {t: res[n] for n, t in items}


async def do_office(ctx: Ctx, path: Path, ext: str, name: str, src, tgt, glossary, out: Path) -> Path:
    ctx.set(0.02, "lecture…")
    slots, save = LOADERS[ext](path)
    if not slots:
        raise RuntimeError("aucun texte à traduire")
    texts = [s.tagged or flat(s.text) for s in slots]
    done = await translate_texts(ctx, texts, src, tgt, glossary, 0.05, 0.9)
    retry = []
    for s, t in zip(slots, texts):
        segs = inline.decode(done[t], s.links) if s.tagged else None
        if segs:
            s.put_segs(segs)
        elif s.tagged:
            retry.append(s)
        else:
            s.put(done[t])
    if retry:
        plain = [flat(s.text) for s in retry]
        again = await translate_texts(ctx, plain, src, tgt, glossary, 0.9, 0.95)
        for s, t in zip(retry, plain):
            s.put(again[t])
    dest = out / f"{name}.{tgt}{ext}"
    save(dest)
    return dest


def pdf_progress(ctx: Ctx):
    """pdf2zh-next draws a rich bar: overall row `translate ━━ 45/100`, stage rows `Stage (i/n) ━━ c/t`."""
    def feed(line: str) -> None:
        line = ANSI_RE.sub("", line).strip()
        if m := BAR_RE.match(line):
            cur, tot = int(m[2]), int(m[3])
            if m[1] == "translate":
                ctx.set(min(cur / max(tot, 1), 0.99))
            elif cur < tot:
                ctx.set(message=f"{m[1]} {cur}/{tot}"[:70])
        elif line:
            ctx.set(message=line[:70])

    return feed


async def do_pdf(ctx: Ctx, path: Path, name: str, src, tgt, glossary, pages: str, work: Path, out: Path, use_ocr: bool = True) -> list[Path]:
    if src == "auto":
        raise RuntimeError("langue source requise pour un PDF")
    if use_ocr and not await ocr.has_text(path):
        ctx.set(0, "PDF sans texte: OCR…")
        scanned = work / "ocr.pdf"
        await ocr.ocr_pdf(ctx, path, scanned)
        path = scanned
    d, ol = cfg["docs"], cfg["ollama"]
    res_dir = work / "out"
    res_dir.mkdir()
    pdf = work / f"{name}.pdf"
    shutil.copy(path, pdf)
    argv = [
        "pdf2zh_next", "--ollama", "--ollama-model", d["pdf_model"] or ol["translate_model"],
        "--ollama-host", ol["url"], "--lang-in", src, "--lang-out", tgt, "--output", str(res_dir),
        "--qps", str(d["qps"]), "--watermark-output-mode", "no_watermark", "--disable-config-auto-save",
    ]
    if not d["auto_glossary"]:
        argv.append("--no-auto-extract-glossary")
    if pages:
        if not PAGES_RE.match(pages):
            raise RuntimeError("pages invalides")
        argv += ["--pages", pages.replace(" ", "")]
    if glossary:
        gfile = work / "glossary.csv"
        with open(gfile, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["source", "target"])
            w.writerows(glossary)
        argv += ["--glossaries", str(gfile)]
    argv.append(str(pdf))

    feed = pdf_progress(ctx)

    ctx.set(0, "attente GPU…")
    async with manager.gpu_lock:
        ctx.set(0, "traduction PDF…")
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "FORCE_COLOR": "1", "NO_COLOR": "1",
               "TERM": "xterm", "COLUMNS": "160"}
        await run_cmd(argv, feed, env=env)
    pdfs = sorted(res_dir.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError("pdf2zh: aucune sortie")
    dests = []
    for f in pdfs:
        dests.append(out / f.name.replace(".no_watermark", ""))
        shutil.move(f, dests[-1])
    return dests


async def run(ctx: Ctx, p: dict) -> str:
    path = Path(p.get("path") or "")
    src, tgt = p.get("src", "en"), p.get("tgt", "fr")
    if not path.is_file():
        raise RuntimeError("fichier introuvable")
    if tgt not in translate.LANGS or (src != "auto" and src not in translate.LANGS):
        raise RuntimeError("langue inconnue")
    ext = path.suffix.lower()
    if ext != ".pdf" and ext not in LOADERS and ext not in CONVERT:
        raise RuntimeError(f"format non supporté: {ext}")
    glossary = translate.parse_glossary(p.get("glossary") or "")
    uploads = (data_dir() / "uploads").resolve()
    name = ocr.upload_name(path)
    work = data_dir() / "tmp" / str(ctx.id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out = output_dir("docs")
    out.mkdir(parents=True, exist_ok=True)
    try:
        if ext == ".pdf":
            dests = await do_pdf(ctx, path, name, src, tgt, glossary, (p.get("pages") or "").strip(), work, out, p.get("ocr", True) is not False)
            ctx.set(1.0, ", ".join(d.name for d in dests))
            return str(out)
        if ext in CONVERT:
            ctx.set(0, "conversion LibreOffice…")
            await run_cmd(
                ["soffice", "--headless", "--convert-to", CONVERT[ext], "--outdir", str(work), str(path)]
            )
            conv = work / f"{path.stem}.{CONVERT[ext]}"
            if not conv.is_file():
                raise RuntimeError("conversion échouée")
            path, ext = conv, "." + CONVERT[ext]
        dest = await do_office(ctx, path, ext, name, src, tgt, glossary, out)
        ctx.set(1.0, dest.name)
        return str(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        orig = Path(p["path"])
        if orig.resolve().is_relative_to(uploads):
            orig.unlink(missing_ok=True)


register("document", run)
