import re
import shutil
from pathlib import Path

from .config import cfg, output_dir
from .convert import need, unique
from . import ollama, plat
from .jobs import Ctx, manager, register
from .ocr import upload_name
from .proc import CmdError, run_cmd
from .util import binpath, HEAVY, src_file, workdir

PCT_RE = re.compile(r"(\d{1,3})%")
FMTS = {"mp3", "flac", "wav"}
MODELS = {"htdemucs", "htdemucs_6s", "htdemucs_ft"}
ENC = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"]}


def unique_dir(base: Path, name: str) -> Path:
    for n in range(1, 1000):
        d = base / (name if n == 1 else f"{name} ({n})")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError("trop de dossiers du même nom")


async def to_wav(src: Path, wav: Path, rate: int, channels: int) -> None:
    await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ar", str(rate),
                   "-ac", str(channels), "-c:a", "pcm_s16le", str(wav)])


def demucs_bin() -> str:
    """demucs du venv Seed-VC (torch ROCm, GPU) s'il existe, sinon [audio] demucs_bin."""
    own = Path(cfg["voice"]["python"]).expanduser().with_name("demucs.exe" if plat.IS_WIN else "demucs")
    return str(own) if own.is_file() else binpath(cfg["audio"]["demucs_bin"])


def demucs_gpu() -> bool:
    return cfg["audio"]["demucs_device"] != "cpu"


async def stems(ctx: Ctx, src: Path, name: str, p: dict, work: Path) -> str:
    a = cfg["audio"]
    need(demucs_bin(), hint="uv tool install demucs (ou scripts/voice-setup.sh)")
    model = p.get("model", "htdemucs")
    fmt = p.get("format", "mp3")
    if model not in MODELS or fmt not in FMTS:
        raise RuntimeError("paramètre invalide")
    wav = work / "input.wav"
    ctx.set(0.02, "préparation audio…")
    await to_wav(src, wav, 44100, 2)
    argv = [demucs_bin(), "-n", model, "-o", str(work / "sep")]
    if a["demucs_device"] != "auto":
        argv += ["-d", a["demucs_device"]]
    if p.get("two_stems"):
        argv += ["--two-stems", "vocals"]
    argv += {"mp3": ["--mp3", "--mp3-bitrate", "256"], "flac": ["--flac"], "wav": ["--int24"]}[fmt]
    argv.append(str(wav))

    def feed(line: str) -> None:
        if m := PCT_RE.search(line):
            ctx.set(0.05 + 0.9 * min(int(m[1]), 100) / 100, f"séparation {m[1]} %")

    async def separate() -> None:
        try:
            await run_cmd(argv, feed)
        except CmdError as e:
            raise RuntimeError(f"{e} (1er lancement: le modèle {model} se télécharge, réseau requis)") from None

    ctx.set(0.05, "en file…")
    async with HEAVY:  # CPU slot first: the global GPU lock is never held while idle behind another job
        if demucs_gpu():
            ctx.set(0.05, "attente GPU…")
            async with manager.gpu_lock:
                if cfg["gpu"]["free_vram"]:
                    await ollama.unload_all()
                ctx.set(0.05, "séparation…")
                await separate()
        else:
            ctx.set(0.05, "séparation…")
            await separate()
    found = sorted((work / "sep").glob(f"{model}/*/*.{fmt}"))
    if not found:
        raise RuntimeError("demucs: aucune piste produite")
    out = output_dir("audio")
    out.mkdir(parents=True, exist_ok=True)
    dest = unique_dir(out, f"{name} (pistes)")
    for f in found:
        shutil.move(f, dest / f.name)
    return str(dest)


async def denoise(ctx: Ctx, src: Path, name: str, p: dict, work: Path) -> str:
    bin_ = binpath(cfg["audio"]["deepfilter_bin"])
    need(bin_, hint="binaire deep-filter: github.com/Rikorose/DeepFilterNet/releases → ~/.local/bin (ou uv tool install deepfilternet + deepfilter_bin = \"deepFilter\")")
    fmt = p.get("format", "wav")
    if fmt not in FMTS:
        raise RuntimeError("paramètre invalide")
    wav = work / "in.wav"
    ctx.set(0.05, "préparation audio…")
    await to_wav(src, wav, 48000, 1)
    clean = work / "clean"
    clean.mkdir()
    ctx.set(0.2, "réduction du bruit…")
    async with HEAVY:
        await run_cmd([bin_, "-o", str(clean), str(wav)])
    res = next(iter(sorted(clean.glob("*.wav"))), None)
    if not res:
        raise RuntimeError("deep-filter: aucune sortie")
    out = output_dir("audio")
    out.mkdir(parents=True, exist_ok=True)
    dest = unique(out, f"{name}.denoised", f".{fmt}")
    try:
        ctx.set(0.9, "encodage…")
        await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(res), *ENC[fmt], str(dest)])
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return str(dest)


async def run(ctx: Ctx, p: dict) -> str:
    path = src_file(p)
    action = p.get("action", "stems")
    if action not in ("stems", "denoise"):
        raise RuntimeError("action inconnue")
    work = workdir(ctx.id, "a")
    try:
        res = await (stems if action == "stems" else denoise)(ctx, path, upload_name(path), p, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ctx.set(1.0, Path(res).name)
    return res


register("audio", run)
