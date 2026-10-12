import json
import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import audio, ollama, player, speech
from .config import cfg, output_dir
from .convert import need, unique
from .jobs import Ctx, manager, register
from .ocr import upload_name
from .proc import run_cmd
from .util import HEAVY, binpath, src_file, workdir
from .voicedsp import FX, chain

# ref = fichier <ref>.wav dans voices_dir (scripts/voice-refs.sh); post = post-traitement DSP
AI_VOICES = [
    ("femme-claire", "Femme claire", "Voix féminine nette, médium", "fr"),
    ("femme-chaleureuse", "Femme chaleureuse", "Voix féminine douce et posée", "fr"),
    ("femme-posee", "Femme grave", "Voix féminine mature, plus grave", "fr"),
    ("homme-pose", "Homme posé", "Voix masculine naturelle", "fr"),
    ("homme-grave", "Homme grave", "Voix masculine basse", "fr"),
    ("homme-jeune", "Homme jeune", "Voix masculine claire et dynamique", "fr"),
    ("homme-narrateur", "Narrateur", "Voix masculine de lecture, régulière", "fr"),
    ("voix-aigue", "Voix jeune aiguë", "Voix aiguë, adolescent", "fr"),
    ("voix-agee", "Voix âgée", "Timbre masculin avec tremblement léger", "fr", "age"),
    ("anonyme", "Voix neutre", "Timbre neutre, identité d'origine masquée", "fr"),
    ("en-femme-claire", "Woman, clear", "Voix féminine anglophone nette", "en"),
    ("en-femme-chaleureuse", "Woman, warm", "Voix féminine anglophone (UK) douce", "en"),
    ("en-homme-pose", "Man, calm", "Voix masculine anglophone (US)", "en"),
    ("en-homme-grave", "Man, deep", "Voix masculine anglophone grave", "en"),
    ("narrateur-en", "Narrator (UK)", "Voix de narrateur britannique", "en"),
]
FORMATS = {"wav": ["-c:a", "pcm_s16le"], "mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "flac": ["-c:a", "flac"], "mkv": ["-c:a", "aac", "-b:a", "192k"]}
INSTALL = "scripts/voice-setup.sh puis scripts/voice-refs.sh --piper"
SLUG_RE = re.compile(r"[^a-z0-9]+")
router = APIRouter()


def voices_dir() -> Path:
    return Path(cfg["voice"]["voices_dir"]).expanduser()


def seedvc_python() -> Path:
    return Path(cfg["voice"]["python"]).expanduser()


def seedvc_dir() -> Path:
    return Path(cfg["voice"]["seedvc_dir"]).expanduser()


def seedvc_ready(live: bool = False) -> bool:
    d = seedvc_dir()
    return seedvc_python().is_file() and (d / ("real-time-gui.py" if live else "inference.py")).is_file()


def demucs_bin() -> str:
    return audio.demucs_bin()


def custom_voices() -> list[dict]:
    out = []
    for meta in sorted((voices_dir() / "custom").glob("*.json")):
        try:
            m = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        out.append({"id": f"c-{meta.stem}", "name": m.get("name", meta.stem), "desc": "Voix ajoutée", "kind": "ai", "lang": m.get("lang", "fr"),
                    "ref": str(meta.with_suffix(".wav")), "post": None, "custom": True})
    return out


def catalogue() -> list[dict]:
    d = voices_dir()
    ai = [{"id": v[0], "name": v[1], "desc": v[2], "kind": "ai", "lang": v[3], "ref": str(d / f"{v[0]}.wav"),
           "post": v[4] if len(v) > 4 else None, "custom": False} for v in AI_VOICES]
    fx = [{"id": f"fx-{k}", "name": n, "desc": ds, "kind": "fx", "lang": "", "ref": None, "post": k, "custom": False}
          for k, (n, ds, _) in FX.items()]
    return ai + custom_voices() + fx


def find(vid: str) -> dict:
    for v in catalogue():
        if v["id"] == vid:
            return v
    raise RuntimeError(f"voix inconnue: {vid}")


def engine_for(v: dict) -> str:
    """seedvc | dsp. Une voix IA n'a pas de repli DSP: l'erreur dit quoi installer."""
    if v["kind"] == "fx":
        return "dsp"
    eng = cfg["voice"]["engine"]
    if eng == "dsp":
        raise RuntimeError(f"la voix « {v['name']} » demande le moteur seedvc (engine = \"dsp\" dans config.toml)")
    if not seedvc_ready():
        raise RuntimeError(f"Seed-VC absent ({seedvc_python()} / {seedvc_dir()}): {INSTALL}")
    if not Path(v["ref"]).is_file():
        raise RuntimeError(f"référence de la voix absente ({Path(v['ref']).name}): scripts/voice-refs.sh --piper")
    return "seedvc"


def describe() -> list[dict]:
    ready_engine = seedvc_ready() and cfg["voice"]["engine"] != "dsp"
    out = []
    for v in catalogue():
        ok = v["kind"] == "fx" or (ready_engine and Path(v["ref"]).is_file())
        out.append({"id": v["id"], "name": v["name"], "desc": v["desc"], "kind": v["kind"], "lang": v["lang"], "ready": ok,
                    "custom": v["custom"]})
    return out


def _env() -> dict:
    import os
    env = dict(os.environ)
    if cfg["voice"]["offline"]:
        env["HF_HUB_OFFLINE"] = "1"
    return env


async def convert_ai(ctx: Ctx, src: Path, ref: str, outdir: Path) -> Path:
    v = cfg["voice"]
    outdir.mkdir()
    argv = [str(seedvc_python()), str(seedvc_dir() / "inference.py"), "--source", str(src), "--target", ref,
            "--output", str(outdir), "--diffusion-steps", str(int(v["file_steps"])), "--inference-cfg-rate", "0.7", "--fp16", "True"]
    await run_cmd(argv, cwd=str(seedvc_dir()), env=_env())
    res = next(iter(sorted(outdir.glob("*.wav"))), None)
    if not res:
        raise RuntimeError("seed-vc: aucune sortie")
    return res


async def dsp_file(src: Path, dest: Path, filt: str) -> None:
    await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-af", filt, "-c:a", "pcm_s16le", str(dest)])


async def run(ctx: Ctx, p: dict) -> str:
    path = src_file(p)
    voice = find(p.get("voice", ""))
    fmt = p.get("format", "wav")
    if fmt not in FORMATS:
        raise RuntimeError("paramètre invalide")
    eng = engine_for(voice)
    separate = bool(p.get("separate", True))
    keep = separate and bool(p.get("keep_music", False))
    if separate:
        need(demucs_bin(), hint="scripts/voice-setup.sh (installe demucs dans le venv Seed-VC)")
    work = workdir(ctx.id, "v")
    try:
        wav = work / "in.wav"
        ctx.set(0.03, "préparation audio…")
        await audio.to_wav(path, wav, 44100, 2)
        vocals, music = wav, None
        gpu = eng == "seedvc" or (separate and audio.demucs_gpu())

        async def job() -> Path:
            nonlocal vocals, music
            if separate:
                ctx.set(0.08, "séparation voix / accompagnement…")
                a = cfg["audio"]
                argv = [demucs_bin(), "-n", "htdemucs", "-o", str(work / "sep"), "--two-stems", "vocals"]
                if a["demucs_device"] != "auto":
                    argv += ["-d", a["demucs_device"]]
                await run_cmd(argv + [str(wav)])
                vocals = next(iter(sorted((work / "sep").glob("htdemucs/*/vocals.*"))), None)
                music = next(iter(sorted((work / "sep").glob("htdemucs/*/no_vocals.*"))), None)
                if not vocals:
                    raise RuntimeError("demucs: aucune piste voix")
            ctx.set(0.4, f"conversion « {voice['name']} »…")
            if eng == "seedvc":
                res = await convert_ai(ctx, vocals, voice["ref"], work / "vc")
            else:
                res = work / "fx.wav"
                await dsp_file(vocals, res, chain(voice["post"]))
            if eng == "seedvc" and voice["post"]:
                post = work / "post.wav"
                await dsp_file(res, post, chain(voice["post"]))
                res = post
            return res

        async with HEAVY:
            if gpu:
                ctx.set(0.03, "attente GPU…")
                async with manager.gpu_lock:
                    if cfg["gpu"]["free_vram"]:
                        await ollama.unload_all()
                    res = await job()
            else:
                res = await job()

        mixed = res
        if keep and music:
            ctx.set(0.9, "mixage…")
            mixed = work / "mix.wav"
            await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(res), "-i", str(music),
                           "-filter_complex", "[0:a]aresample=44100,aformat=channel_layouts=stereo[a];"
                           "[1:a]aresample=44100,aformat=channel_layouts=stereo[b];"
                           "[a][b]amix=inputs=2:duration=longest:normalize=0", "-c:a", "pcm_s16le", str(mixed)])
        out = output_dir("audio")
        out.mkdir(parents=True, exist_ok=True)
        dest = unique(out, f"{upload_name(path)}.voix-{voice['id']}", f".{fmt}")
        ctx.set(0.95, "encodage…")
        try:
            if fmt == "mkv":
                await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-i", str(mixed), "-map", "0:v",
                               "-map", "1:a", "-c:v", "copy", *FORMATS["mkv"], "-shortest", str(dest)])
            else:
                await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(mixed), *FORMATS[fmt], str(dest)])
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ctx.set(1.0, dest.name)
    return str(dest)


register("voice", run)


class PreviewIn(BaseModel):
    voice: str


class AddIn(BaseModel):
    path: str
    name: str
    rights: bool = False
    lang: str = "fr"


@router.get("/api/voice/voices")
async def voices():
    return {"voices": describe(), "engine": cfg["voice"]["engine"], "seedvc": seedvc_ready(), "live_ai": seedvc_ready(live=True)}


@router.post("/api/voice/preview")
async def preview(body: PreviewIn):
    """Joue la référence d'une voix IA, ou une phrase synthétisée passée dans l'effet."""
    try:
        v = find(body.voice)
    except RuntimeError as e:
        raise HTTPException(404, str(e))
    if not player.available():
        raise HTTPException(501, "aucun lecteur audio installé")
    if v["kind"] == "ai":
        if not Path(v["ref"]).is_file():
            raise HTTPException(404, "référence absente: scripts/voice-refs.sh --piper")
        return {"player": await player.play(v["ref"])}
    cache = output_dir("audio") / ".listen"
    cache.mkdir(parents=True, exist_ok=True)
    raw, dest = cache / f"preview-{v['id']}.raw.wav", cache / f"preview-{v['id']}.wav"
    try:
        bin_ = binpath(cfg["tts"]["bin"])
        need(bin_, hint="uv tool install piper-tts")
        onnx = speech.voice_for("fr")
        txt = cache / "preview.txt"
        txt.write_text("Bonjour, ceci est un essai de la voix choisie.", encoding="utf-8")
        with open(txt, "rb") as f:
            await run_cmd([bin_, "-m", str(onnx), "-f", str(raw)], stdin=f)
        await dsp_file(raw, dest, chain(v["post"]))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    finally:
        raw.unlink(missing_ok=True)
    return {"player": await player.play(str(dest))}


@router.post("/api/voice/voices")
async def add_voice(body: AddIn):
    from .util import upload_paths
    if not body.rights:
        raise HTTPException(400, "il faut confirmer avoir le droit d'utiliser cette voix")
    ups = upload_paths({"path": body.path})
    name = body.name.strip()[:40]
    if not ups or not ups[0].is_file() or not name:
        raise HTTPException(400, "fichier ou nom manquant")
    slug = SLUG_RE.sub("-", name.lower()).strip("-") or "voix"
    d = voices_dir() / "custom"
    d.mkdir(parents=True, exist_ok=True)
    wav = d / f"{slug}.wav"
    if wav.exists():
        raise HTTPException(409, "une voix porte déjà ce nom")
    try:
        await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(ups[0]), "-vn", "-t", "30", "-ar", "22050",
                       "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        sec = (wav.stat().st_size - 44) / (22050 * 2)
        if sec < 3:
            wav.unlink(missing_ok=True)
            raise HTTPException(400, "échantillon trop court (3 s minimum, 10 à 30 s idéal)")
    except RuntimeError as e:
        wav.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    (d / f"{slug}.json").write_text(json.dumps({"name": name, "rights": True, "lang": body.lang if body.lang in ("fr", "en") else "fr", "added": time.time()}))
    ups[0].unlink(missing_ok=True)
    return {"id": f"c-{slug}"}


@router.delete("/api/voice/voices/{vid}")
async def delete_voice(vid: str):
    if not vid.startswith("c-") or not re.fullmatch(r"c-[a-z0-9-]+", vid):
        raise HTTPException(400, "seules les voix ajoutées se suppriment")
    d = voices_dir() / "custom"
    for ext in (".wav", ".json"):
        (d / f"{vid[2:]}{ext}").unlink(missing_ok=True)
    return {"ok": True}
