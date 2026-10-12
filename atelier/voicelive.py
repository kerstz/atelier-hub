"""Direct: micro -> conversion -> micro virtuel PipeWire. Le moteur audio tourne côté serveur (un <audio>
dans WebKitGTK plante); l'interface ne fait que piloter. Un job `voice_live` tient le verrou GPU tant que la
session dure, donc file, annulation et historique viennent du gestionnaire de jobs."""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import plat
from .config import cfg
from .jobs import Ctx, manager, register
from .voice import engine_for, find, seedvc_dir, seedvc_python, seedvc_ready
from .voicedsp import chain

SINK, MIC = "atelier_vc_sink", "atelier_vc_mic"
WORKER = Path(__file__).with_name("voicelive_worker.py")
router = APIRouter()
STATE: dict = {"running": False}
_ctl: asyncio.Queue | None = None


def _kill(p: asyncio.subprocess.Process | None) -> None:
    if p and p.returncode is None:
        plat.kill_tree(p, force=True)


async def _spawn(argv: list[str], **kw) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(*argv, **plat.spawn_kw(), stdin=kw.pop("stdin", asyncio.subprocess.DEVNULL),
                                                stderr=asyncio.subprocess.DEVNULL, **kw)


def _win_mic() -> str:
    from . import winaudio
    return winaudio.VIRTUAL_MIC


def _loopback_argv() -> list[str]:
    return ["pw-loopback",
            f"--capture-props=media.class=Audio/Sink node.name={SINK} node.description=\"Atelier (entrée voix)\"",
            f"--playback-props=media.class=Audio/Source node.name={MIC} node.description=\"Micro Atelier (voix)\""]


def _dsp_argv(source: str, fx: str) -> list[str]:
    if plat.IS_WIN:
        from .winaudio import VIRTUAL_SINK
        return [*plat.audio_cmd(), "dsp", "--source", "" if source == "default" else source, "--sink", VIRTUAL_SINK,
                "--af", chain(fx), "--ffmpeg", shutil.which("ffmpeg") or "ffmpeg"]
    return ["ffmpeg", "-nostdin", "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay", "-f", "pulse", "-i", source,
            "-af", chain(fx), "-ar", "48000", "-ac", "1", "-f", "pulse", "-buffer_duration", "20", SINK]


def _worker_argv(source: str, ref: str) -> list[str]:
    v = cfg["voice"]
    from .winaudio import VIRTUAL_SINK
    argv = [str(seedvc_python()), str(WORKER), "--source", "" if source in ("default", "@DEFAULT_SOURCE@") else source,
            "--sink", VIRTUAL_SINK if plat.IS_WIN else SINK, "--voice", ref, "--block", str(v["live_block"]),
            "--steps", str(int(v["live_steps"])), "--cfg", str(v["live_cfg"]), "--gate-db", str(v["live_gate_db"]),
            "--extra-right", str(v["live_extra_right"])]
    if v["live_checkpoint"]:
        argv += ["--checkpoint", os.path.expanduser(v["live_checkpoint"]), "--config", os.path.expanduser(v["live_config"])]
    return argv


def _win_check(eng: str) -> None:
    """Fail early with the fix when the virtual cable or PortAudio is missing."""
    try:
        import sounddevice as sd
    except Exception as e:
        raise RuntimeError(f"sounddevice indisponible: {e}") from None
    from . import winaudio
    devs = winaudio._devices(sd)
    try:
        winaudio.pick(devs, winaudio.VIRTUAL_SINK, "output")
    except RuntimeError:
        raise RuntimeError("micro virtuel absent: installer VB-Audio Cable (vb-audio.com/Cable), puis relancer") from None


async def live(ctx: Ctx, p: dict) -> None:
    global _ctl
    voice = find(p.get("voice", ""))
    eng = engine_for(voice)
    if eng == "seedvc" and not seedvc_ready(live=True):
        raise RuntimeError("Seed-VC absent ou incomplet: scripts/voice-setup.sh")
    if plat.IS_WIN:
        _win_check(eng)
    else:
        for b in ("pw-loopback", "ffmpeg" if eng == "dsp" else "parec"):
            if not shutil.which(b):
                raise RuntimeError(f"{b} introuvable")
    source = p.get("source") or ("default" if eng == "dsp" else "@DEFAULT_SOURCE@")
    deadline = time.monotonic() + float(cfg["voice"]["live_max_minutes"]) * 60
    _ctl = asyncio.Queue()
    STATE.clear()
    STATE.update(running=True, job=ctx.id, voice=voice["id"], engine=eng, source=source, ready=False, stats={}, bypass=False,
                 mute=False, mic=_win_mic() if plat.IS_WIN else MIC)
    loop = proc = reader = None
    try:
        if not plat.IS_WIN:
            loop = await _spawn(_loopback_argv())
            await asyncio.sleep(0.4)
            if loop.returncode is not None:
                raise RuntimeError("pw-loopback a quitté: PipeWire actif ?")
        cur = voice
        while True:
            if eng == "seedvc":
                ctx.set(0.05, "chargement du modèle…")
                env = {**os.environ, **({"HF_HUB_OFFLINE": "1"} if cfg["voice"]["offline"] else {}),
                       **({"ATELIER_AUDIO_CMD": json.dumps(plat.audio_cmd())} if plat.IS_WIN else {})}
                proc = await _spawn(_worker_argv(source, cur["ref"]), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                    cwd=str(seedvc_dir()), env=env)
                reader = asyncio.create_task(_read_stats(ctx, proc))
            else:
                proc = await _spawn(_dsp_argv(source, cur["post"]))
                STATE["ready"] = True
                ctx.set(0.5, f"en direct · {cur['name']}")
            exit_t = asyncio.create_task(proc.wait())
            while True:
                cmd_t = asyncio.create_task(_ctl.get())
                done, _ = await asyncio.wait({exit_t, cmd_t}, timeout=max(0.5, deadline - time.monotonic()),
                                             return_when=asyncio.FIRST_COMPLETED)
                if time.monotonic() >= deadline:
                    cmd_t.cancel()
                    ctx.set(1.0, "durée maximale atteinte")
                    return
                if exit_t in done:
                    cmd_t.cancel()
                    raise RuntimeError(f"le moteur voix s'est arrêté (code {proc.returncode}); voir le journal de la tâche")
                if cmd_t not in done:
                    cmd_t.cancel()
                    continue
                cmd = cmd_t.result()
                if cmd.get("op") == "stop":
                    return
                STATE.update({k: cmd[k] for k in ("bypass", "mute") if k in cmd})
                if "voice" in cmd:
                    nv = find(cmd["voice"])
                    if engine_for(nv) != eng:
                        raise RuntimeError("changement de moteur en direct impossible: arrêter puis relancer")
                    cur = nv
                    STATE["voice"] = nv["id"]
                    if eng == "seedvc":
                        _send(proc, {"voice": nv["ref"]})
                    else:
                        exit_t.cancel()
                        _kill(proc)
                        await proc.wait()
                        break  # relance ffmpeg avec la nouvelle chaîne
                if eng == "seedvc":
                    _send(proc, {k: cmd[k] for k in ("bypass", "mute", "gate_db", "gain_db") if k in cmd})
    finally:
        STATE.clear()
        STATE["running"] = False
        _ctl = None
        if reader:
            reader.cancel()
        _kill(proc)
        _kill(loop)


def _send(proc, msg: dict) -> None:
    if msg and proc.stdin and not proc.stdin.is_closing():
        proc.stdin.write((json.dumps(msg) + "\n").encode())


async def _read_stats(ctx: Ctx, proc) -> None:
    while line := await proc.stdout.readline():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("ready"):
            STATE.update(ready=True, latency_ms=m.get("latency_ms"))
            ctx.set(0.5, "en direct")
        elif "infer_ms" in m:
            STATE["stats"] = m
            ctx.set(None, f"en direct · {m['infer_ms']} ms/bloc" + (f" · {m['overruns']} retard(s)" if m["overruns"] else ""))


register("voice_live", live, gpu=lambda p: p.get("_gpu", False), frees_vram=True)


class StartIn(BaseModel):
    voice: str
    source: str = ""


class SetIn(BaseModel):
    voice: str | None = None
    bypass: bool | None = None
    mute: bool | None = None
    gate_db: float | None = None
    gain_db: float | None = None


@router.get("/api/voice/inputs")
async def inputs():
    out = []
    if plat.IS_WIN:
        try:
            p = await asyncio.create_subprocess_exec(*plat.audio_cmd(), "list", stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.DEVNULL, **plat.spawn_kw())
            data, _ = await asyncio.wait_for(p.communicate(), 10)
            names = json.loads(data or b"{}").get("inputs", [])
            out = [{"name": n, "desc": n} for n in names if "cable" not in n.lower()]
        except (OSError, ValueError, asyncio.TimeoutError):
            pass
        return {"inputs": out}
    try:
        p = await asyncio.create_subprocess_exec("pactl", "-f", "json", "list", "sources", stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
        data, _ = await asyncio.wait_for(p.communicate(), 5)
        for s in json.loads(data or b"[]"):
            n = s.get("name", "")
            if n.endswith(".monitor") or n == MIC or n.startswith("atelier_vc"):
                continue
            out.append({"name": n, "desc": s.get("description", n)})
    except (OSError, ValueError, asyncio.TimeoutError):
        pass
    return {"inputs": out}


@router.get("/api/voice/live")
async def live_state():
    return {k: v for k, v in STATE.items()} if STATE.get("running") else {"running": False}


@router.post("/api/voice/live/start")
async def live_start(body: StartIn):
    if STATE.get("running") or any(_is_live(j) for j in list(manager.tasks)):
        raise HTTPException(409, "une session voix est déjà active")
    try:
        v = find(body.voice)
        eng = engine_for(v)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if eng == "seedvc" and manager.gpu_lock.locked():
        raise HTTPException(409, "GPU occupé par une autre tâche: la voix en direct ne se met pas en file")
    return manager.submit("voice_live", f"Voix en direct : {v['name']}",
                          {"voice": v["id"], "source": body.source, "_gpu": eng == "seedvc"})


def _is_live(jid: int) -> bool:
    from . import db
    row = db.get(jid)
    return bool(row) and row.get("kind") == "voice_live"


@router.post("/api/voice/live/set")
async def live_set(body: SetIn):
    if not STATE.get("running") or _ctl is None:
        raise HTTPException(409, "aucune session voix active")
    cmd = {k: v for k, v in body.model_dump().items() if v is not None}
    _ctl.put_nowait(cmd)
    return {"ok": True}


@router.post("/api/voice/live/stop")
async def live_stop():
    if _ctl is not None:
        _ctl.put_nowait({"op": "stop"})
    return {"ok": True}
