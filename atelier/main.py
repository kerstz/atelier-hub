import asyncio
import re
import shutil
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audio, convert, plat, db, docs, engines, gpu, grammar, hw, images, joblog, maint, media, player, speech, ocr, ollama, services, subs, summary, translate, voice, voicelive, youtube  # noqa: F401
from .config import ROOT, VERSION, cfg, data_dir, output_dir
from .diagnostic import build_zip
from .update import check as check_update
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
            media.purge_cache()
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
    media.purge_cache()
    joblog.purge()
    (data_dir() / "uploads").mkdir(exist_ok=True)
    shutil.rmtree(data_dir() / "tmp", ignore_errors=True)  # no job survives a restart: leftovers are garbage
    (data_dir() / "tmp").mkdir(exist_ok=True)
    purge_uploads()
    janitor = asyncio.create_task(_janitor())
    yield
    janitor.cancel()
    await grammar.stop()
    tasks = list(manager.tasks.values())
    for t in tasks:
        t.cancel()
    if tasks:  # let handlers run their finally blocks (work dirs, partial outputs)
        await asyncio.wait(tasks, timeout=8)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


APP_CSP = {  # sub-apps served under their own paths: stricter than the UI, which keeps frame-ancestors only
    "/vert": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
             "img-src 'self' data: blob:; connect-src 'self' blob: data:; worker-src 'self' blob:; frame-ancestors 'self'",
    "/harper": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; frame-ancestors 'self'",
}


def _csp(path: str) -> str:
    for prefix, policy in APP_CSP.items():
        if path == prefix or path.startswith(prefix + "/"):
            return policy
    return "frame-ancestors 'self'"


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
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):  # UI files: revalidate (etag) so an update never mixes old and new JS
        resp.headers.setdefault("cache-control", "no-cache")
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Content-Security-Policy"] = _csp(request.url.path)
        resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


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
    vram = await asyncio.to_thread(gpu.vram) if plat.IS_MAC else gpu.vram()  # mac: sync HTTP to Ollama, off the event loop
    return {"vram": vram, "ollama": await ollama.loaded(), "gpu_busy": manager.gpu_lock.locked(), "version": VERSION}


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
    s = cfg["server"]
    limit, reserve = int(s["max_upload_mb"]) << 20, int(s["min_free_gb"]) << 30
    declared = int(request.headers.get("content-length") or 0) if (request.headers.get("content-length") or "").isdigit() else 0
    if declared > limit:
        raise HTTPException(413, f"fichier trop gros (max {s['max_upload_mb']} Mo)")
    if shutil.disk_usage(dest.parent).free - declared < reserve:
        raise HTTPException(507, "espace disque insuffisant")
    written = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, f"fichier trop gros (max {s['max_upload_mb']} Mo)")
                if written // (64 << 20) != (written - len(chunk)) // (64 << 20) and shutil.disk_usage(dest.parent).free < reserve:
                    raise HTTPException(507, "espace disque insuffisant")
                await asyncio.to_thread(f.write, chunk)
    except BaseException:
        dest.unlink(missing_ok=True)  # never leave a partial upload behind
        raise
    return {"path": str(dest), "name": safe}


@app.post("/api/youtube/probe")
async def youtube_probe(body: ProbeIn):
    try:
        return await youtube.probe(body.url)
    except FileNotFoundError as e:
        raise HTTPException(400, plat.missing_tool(e) or str(e))
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
    plat.open_folder(str(folder))
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


app.include_router(voice.router)
app.include_router(media.router)
app.include_router(voicelive.router)


@app.get("/api/deps")
async def deps():
    return await maint.deps()


@app.get("/api/update")
async def update():
    return await asyncio.to_thread(check_update)


@app.get("/api/diagnostic")
async def diagnostic():
    return Response(await build_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="atelier-diagnostic.zip"'})


@app.get("/api/setup")
async def setup():
    rows = await maint.deps()
    return {**maint.setup_info(rows), "rows": rows}


@app.post("/api/setup/run")
async def setup_run(tier: str = "minimal"):
    """Windows installer build only: open the tool installer (win-setup.ps1) in its own console window."""
    if tier not in ("minimal", "standard", "full"):
        raise HTTPException(400, "tier inconnu")
    import subprocess
    import sys
    script = Path(sys.executable).parent / "scripts" / "win-setup.ps1"
    if not (plat.NT and plat.FROZEN and script.is_file()):
        raise HTTPException(400, "installation automatique disponible seulement avec l'installeur Windows")
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", str(script),
                      "-Tier", tier, "-Models"], creationflags=0x10)  # CREATE_NEW_CONSOLE
    return {"ok": True}


TEXT_EXT = {".srt", ".vtt", ".txt", ".md", ".json", ".csv"}
VIEW_MAX = 2 << 20


@app.get("/api/jobs/{jid}/view")
async def job_view(jid: int):
    """Text result (subtitles, transcript, summary…) for the in-app viewer."""
    p = _job_file(jid)
    if not p or p.suffix.lower() not in TEXT_EXT:
        raise HTTPException(404, "pas de résultat texte")
    if p.stat().st_size > VIEW_MAX:
        raise HTTPException(413, "fichier trop gros pour l'aperçu: le télécharger")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a"}


@app.post("/api/jobs/{jid}/play")
async def job_play(jid: int):
    """Play a finished job's audio file on the machine speakers (the browser's <audio> is unsafe in WebKitGTK)."""
    p = _job_file(jid)
    if not p or p.suffix.lower() not in AUDIO_EXT:
        raise HTTPException(404, "pas de fichier audio")
    if not player.available():
        raise HTTPException(501, "aucun lecteur audio installé")
    return {"playing": True, "player": await player.play(str(p))}


@app.post("/api/play/stop")
async def play_stop():
    await player.stop()
    return {"playing": False}


@app.get("/api/play")
async def play_state():
    return {"playing": player.playing(), "player": player.available()}


@app.get("/api/profile")
async def profile(refresh: bool = False):
    if refresh:
        hw.profile(refresh=True)
    return await engines.describe()


@app.get("/api/disk")
async def disk():
    return await maint.disk()


@app.post("/api/disk/clean/{target}")
async def disk_clean(target: str):
    try:
        return {"freed": await maint.clean(target)}
    except KeyError:
        raise HTTPException(404, "cible inconnue")


@app.get("/api/jobs/{jid}/file")
async def job_file(jid: int):
    job = db.get(jid)
    p = maint.primary_file(job) if job else None
    if not p:
        raise HTTPException(404, "pas de fichier")
    return {"path": str(p), "name": p.name}


GLOSS_NAME_RE = re.compile(r"^[\w .()'\-]{1,60}$")


class GlossaryIn(BaseModel):
    text: str


@app.get("/api/glossaries")
async def glossaries():
    return db.glossaries()


@app.put("/api/glossaries/{name}")
async def glossary_put(name: str, body: GlossaryIn):
    if not GLOSS_NAME_RE.match(name) or len(body.text) > 100_000:
        raise HTTPException(400, "nom ou contenu invalide")
    db.glossary_put(name.strip(), body.text)
    return {"ok": True}


@app.delete("/api/glossaries/{name}")
async def glossary_delete(name: str):
    if not db.glossary_delete(name):
        raise HTTPException(404, "glossaire inconnu")
    return {"ok": True}


@app.get("/api/glossaries/{name}/export")
async def glossary_export(name: str):
    g = db.glossary_get(name)
    if not g:
        raise HTTPException(404, "glossaire inconnu")
    return PlainTextResponse(g["text"], headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.txt"})


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
            while q not in manager.dropped:
                try:
                    event, data = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {event}\ndata: {data}\n\n"
            # fell behind: end the stream; EventSource reconnects and the page reloads /api/jobs
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class GrammarIn(BaseModel):
    text: str
    lang: str = "fr"


@app.get("/api/grammar/status")
async def grammar_status():
    return await grammar.status(data_dir())


@app.post("/api/grammar/check")
async def grammar_check(body: GrammarIn):
    try:
        return {"matches": await grammar.check(body.text, body.lang)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(503, plat.localize(str(e)) or "LanguageTool indisponible")


@app.post("/api/grammar/stop")
async def grammar_stop():
    await grammar.stop()
    return {"ok": True}


class _Revalidate(StaticFiles):  # VERT rebuilds keep the same URLs: HTML/wasm must not go stale
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        immutable = path.startswith("_app/immutable")
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return r


_vert = data_dir() / "vert"
if (_vert / "index.html").is_file():
    app.mount("/vert", _Revalidate(directory=_vert, html=True), name="vert")
if (_hd := grammar.harper_dir(data_dir())):
    app.mount("/harper", _Revalidate(directory=_hd), name="harper")
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
