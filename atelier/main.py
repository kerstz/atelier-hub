import asyncio
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, docs, gpu, ollama, services, subs, translate, youtube  # noqa: F401
from .config import ROOT, data_dir, output_dir
from .jobs import KINDS, manager

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    output_dir().mkdir(parents=True, exist_ok=True)
    for sub in ("youtube", "subs", "docs"):
        output_dir(sub).mkdir(exist_ok=True)
    up = data_dir() / "uploads"
    up.mkdir(exist_ok=True)
    for f in up.iterdir():
        if f.is_file() and time.time() - f.stat().st_mtime > 2 * 86400:
            f.unlink(missing_ok=True)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if urlparse("//" + request.headers.get("host", "")).hostname not in LOCAL_HOSTS:
        return PlainTextResponse("forbidden", status_code=403)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in LOCAL_HOSTS:
        return PlainTextResponse("forbidden", status_code=403)
    return await call_next(request)


class JobIn(BaseModel):
    kind: str
    title: str | None = None
    params: dict = {}


class ProbeIn(BaseModel):
    url: str


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
    db.clear_finished()
    return {"ok": True}


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: int):
    return {"ok": manager.cancel(jid)}


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
