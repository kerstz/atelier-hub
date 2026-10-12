import asyncio
import re
import shutil
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audio, convert, db, docs, gpu, images, joblog, speech, ocr, ollama, services, subs, summary, translate, youtube  # noqa: F401
from .config import ROOT, data_dir, output_dir
from .jobs import KINDS, manager
from .util import missing_uploads, upload_paths

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


UPLOAD_TTL = 2 * 86400


def purge_uploads() -> None:
    """Delete uploads older than the TTL, except files an active job still reads."""
    used = {p for params in db.active_params() for p in upload_paths(params)}
    for f in (data_dir() / "uploads").iterdir():
        try:
            if f.is_file() and time.time() - f.stat().st_mtime > UPLOAD_TTL and f.resolve() not in used:
                f.unlink(missing_ok=True)
        except OSError:
            pass


async def _janitor() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            purge_uploads()
            speech.purge_listen()
            joblog.purge()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    output_dir().mkdir(parents=True, exist_ok=True)
    for sub in ("youtube", "subs", "docs", "convert", "audio", "images"):
        output_dir(sub).mkdir(exist_ok=True)
    speech.purge_listen()
    joblog.purge()
    (data_dir() / "uploads").mkdir(exist_ok=True)
    shutil.rmtree(data_dir() / "tmp", ignore_errors=True)  # no job survives a restart: leftovers are garbage
    (data_dir() / "tmp").mkdir(exist_ok=True)
    purge_uploads()
    janitor = asyncio.create_task(_janitor())
    yield
    janitor.cancel()
    tasks = list(manager.tasks.values())
    for t in tasks:
        t.cancel()
    if tasks:  # let handlers run their finally blocks (work dirs, partial outputs)
        await asyncio.wait(tasks, timeout=8)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if urlparse("//" + request.headers.get("host", "")).hostname not in LOCAL_HOSTS:
        return PlainTextResponse("forbidden", status_code=403)
    origin = request.headers.get("origin")
    if origin:
        o = urlparse(origin)
        # same origin only: scheme + host + port must equal what the browser used to reach us
        if o.scheme != "http" or o.netloc != request.headers.get("host", ""):
            return PlainTextResponse("forbidden", status_code=403)
    # other local web apps (same-site, other port) and cross-site pages can't drive the API, GET included
    if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return PlainTextResponse("forbidden", status_code=403)
    return await call_next(request)


class JobIn(BaseModel):
    kind: str
    title: str | None = None
    params: dict = {}


class ProbeIn(BaseModel):
    url: str


class DetectIn(BaseModel):
    path: str


class UnloadIn(BaseModel):
    model: str


@app.get("/api/system")
async def system():
    return {"vram": gpu.vram(), "ollama": await ollama.loaded(), "gpu_busy": manager.gpu_lock.locked()}


@app.post("/api/ollama/unload")
async def unload(body: UnloadIn):
    try:
        await ollama.unload(body.model)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ollama: {e}")
    return {"ok": True}


@app.post("/api/upload")
async def upload(request: Request, name: str):
    safe = re.sub(r"[^\w.\- ]", "_", Path(name).name)[:120] or "file"
    dest = data_dir() / "uploads" / f"{uuid.uuid4().hex[:8]}-{safe}"
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    return {"path": str(dest), "name": safe}


@app.post("/api/youtube/probe")
async def youtube_probe(body: ProbeIn):
    try:
        return await youtube.probe(body.url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except asyncio.TimeoutError:
        raise HTTPException(504, "délai dépassé")


@app.get("/api/langs")
async def langs():
    return translate.lang_list()


@app.get("/api/translations")
async def translations():
    return db.recent_translations()


@app.post("/api/translations/clear")
async def clear_translations():
    db.clear_translations()
    return {"ok": True}


@app.get("/api/jobs")
async def jobs():
    return db.recent()


@app.post("/api/jobs")
async def create_job(body: JobIn):
    if body.kind not in KINDS:
        raise HTTPException(400, f"type inconnu: {body.kind}")
    return manager.submit(body.kind, body.title or body.kind, body.params)


@app.post("/api/jobs/clear")
async def clear_jobs():
    joblog.remove([j["id"] for j in db.recent(100000) if j["status"] in ("done", "failed", "cancelled")])
    db.clear_finished()
    return {"ok": True}


@app.get("/api/jobs/{jid}/log")
async def job_log(jid: int):
    if not db.get(jid):
        raise HTTPException(404, "tâche inconnue")
    return PlainTextResponse(joblog.read(jid) or "(aucune sortie de commande enregistrée)")


@app.post("/api/jobs/{jid}/retry")
async def retry_job(jid: int):
    job = db.get(jid)
    if not job:
        raise HTTPException(404, "tâche inconnue")
    if job["status"] not in ("failed", "cancelled"):
        raise HTTPException(400, "seules les tâches échouées ou annulées se relancent")
    if job["kind"] not in KINDS:
        raise HTTPException(400, f"type inconnu: {job['kind']}")
    params = db.params(jid)
    if missing_uploads(params):
        raise HTTPException(410, "fichier source supprimé: relancer depuis l'onglet")
    return manager.submit(job["kind"], job["title"], params)


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: int):
    return {"ok": manager.cancel(jid)}


@app.get("/api/jobs/{jid}/result")
async def job_result(jid: int):
    job = db.get(jid)
    path = Path(job["output"] or "").resolve() if job else None
    if not path or not path.is_file() or path.suffix != ".md" or not path.is_relative_to(output_dir().resolve()):
        raise HTTPException(404, "pas de résultat texte")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.post("/api/jobs/{jid}/open")
async def open_job(jid: int):
    job = db.get(jid)
    if not job or not job["output"]:
        raise HTTPException(404, "pas de sortie")
    path = Path(job["output"]).resolve()
    folder = path if path.is_dir() else path.parent
    if not folder.is_relative_to(output_dir().resolve()):
        raise HTTPException(403, "hors dossier de sortie")
    await asyncio.create_subprocess_exec(
        "xdg-open", str(folder), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True}


def _uploaded(path: str) -> Path:
    p = Path(path).resolve()
    if not p.is_file() or not p.is_relative_to((data_dir() / "uploads").resolve()):
        raise HTTPException(404, "fichier introuvable")
    return p


def _job_file(jid: int) -> Path | None:
    job = db.get(jid)
    if not job or job["status"] != "done" or not job["output"]:
        return None
    p = Path(job["output"]).resolve()
    return p if p.is_file() and p.is_relative_to(output_dir().resolve()) else None


@app.get("/api/convert/catalog")
async def convert_catalog():
    return convert.catalog()


@app.post("/api/convert/detect")
async def convert_detect(body: DetectIn):
    return await convert.detect(_uploaded(body.path))


@app.get("/api/jobs/{jid}/download")
async def job_download(jid: int):
    p = _job_file(jid)
    if not p:
        raise HTTPException(404, "pas de fichier")
    return FileResponse(p, filename=p.name)


def _zip(files: list[Path], dest: Path) -> None:
    with zipfile.ZipFile(dest, "w") as z:
        for f in files:
            z.write(f, f.name, zipfile.ZIP_STORED if f.suffix.lower() in convert.COMPRESSED else zipfile.ZIP_DEFLATED)


@app.get("/api/convert/zip")
async def convert_zip(ids: str):
    try:
        wanted = [int(i) for i in ids.split(",") if i][:500]
    except ValueError:
        raise HTTPException(400, "ids invalides")
    files = list(dict.fromkeys(p for p in map(_job_file, wanted) if p))
    if not files:
        raise HTTPException(404, "aucun fichier prêt")
    tmp = data_dir() / "tmp"
    tmp.mkdir(exist_ok=True)
    dest = tmp / f"zip-{uuid.uuid4().hex[:8]}.zip"
    await asyncio.to_thread(_zip, files, dest)
    return FileResponse(dest, filename="atelier-convert.zip", media_type="application/zip",
                        background=BackgroundTask(dest.unlink, missing_ok=True))


@app.get("/api/services")
async def services_list():
    return await services.status()


@app.post("/api/services/{sid}/{action}")
async def services_act(sid: str, action: str):
    try:
        await services.act(sid, action)
    except KeyError:
        raise HTTPException(404, "service ou action inconnu")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.get("/api/events")
async def events():
    q = manager.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    event, data = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {event}\ndata: {data}\n\n"
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
