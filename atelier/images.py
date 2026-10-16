import os
import re
import shutil
from pathlib import Path

from . import plat
from .config import cfg, output_dir
from .convert import need, unique
from .jobs import Ctx, register
from .ocr import upload_name
from .proc import CmdError, run_cmd
from .util import binpath, HEAVY, src_file, workdir

PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")
MODELS = {"photo": "realesrgan-x4plus", "anime": "realesrgan-x4plus-anime"}
REMBG_MODELS = {"u2net", "isnet-general-use", "u2net_human_seg", "isnet-anime", "silueta"}
MAX_PIXELS = 24_000_000  # input cap for x4 (output = 16x)


async def size(path: Path) -> tuple[int, int]:
    if not shutil.which("vipsheader"):
        out: list[str] = []
        await run_cmd(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)], out.append)
        w, h = out[-1].strip().split(",")[:2]
        return int(w), int(h)
    w: list[str] = []
    h: list[str] = []
    await run_cmd(["vipsheader", "-f", "width", str(path)], w.append)
    await run_cmd(["vipsheader", "-f", "height", str(path)], h.append)
    return int(w[-1]), int(h[-1])


async def upscale(ctx: Ctx, src: Path, dest: Path, factor: int, style: str) -> None:
    d = cfg["images"]
    zip = "realesrgan-ncnn-vulkan-20220424-macos.zip" if plat.IS_MAC else "zip ncnn-vulkan ubuntu"
    need(binpath(d["realesrgan_bin"]), hint=f"{zip} de github.com/xinntao/Real-ESRGAN/releases → ~/.local/opt/realesrgan, puis [images] realesrgan_bin")
    w, h = await size(src)
    if w * h > (MAX_PIXELS if factor == 4 else MAX_PIXELS // 2):
        raise RuntimeError(f"image trop grande ({w}x{h}) pour ×{factor}")
    work = workdir(ctx.id, "u")
    try:
        big = work / "x4.png"
        argv = [binpath(d["realesrgan_bin"]), "-i", str(src), "-o", str(big), "-n", MODELS.get(style, MODELS["photo"]),
                "-s", "4", "-f", "png", "-g", str(d["gpu_id"])]
        if d["models_dir"]:
            argv += ["-m", str(Path(d["models_dir"]).expanduser())]
        hi = 0.85 if factor == 2 else 0.98

        def feed(line: str) -> None:
            if m := PCT_RE.search(line):
                ctx.set(min(float(m[1]) / 100 * hi, hi), f"agrandissement {float(m[1]):.0f} %")

        ctx.set(0, "attente GPU…")
        await run_cmd(argv, feed)
        if not big.is_file():
            raise RuntimeError("realesrgan: aucune sortie")
        if factor == 2:
            ctx.set(0.9, "réduction ×2…")
            await run_cmd(["vips", "resize", str(big), str(dest), "0.5", "--kernel", "lanczos3"], env=_quiet())
        else:
            shutil.move(big, dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _quiet() -> dict:
    return {**os.environ, "VIPS_WARNING": "0"}


async def rembg(ctx: Ctx, src: Path, dest: Path, model: str) -> None:
    bin_ = binpath(cfg["images"]["rembg_bin"])
    need(bin_, hint='uv tool install "rembg[cpu,cli]"')
    ctx.set(0.1, "détourage…")
    async with HEAVY:
        try:
            await run_cmd([bin_, "i", "-m", model, str(src), str(dest)])
        except CmdError as e:
            raise RuntimeError(f"{e} (1er lancement: le modèle {model} se télécharge, réseau requis)") from None


ZONES = {"br": (1, 1), "bl": (0, 1), "tr": (1, 0), "tl": (0, 0), "c": (0.5, 0.5)}


async def watermark(ctx: Ctx, src: Path, dest: Path, zone: str, w_pct: float, h_pct: float) -> None:
    """Efface un filigrane rectangulaire par interpolation (ffmpeg delogo): net sur un logo discret, flou sur
    une grande zone ou un motif en travers de l'image."""
    if zone not in ZONES:
        raise RuntimeError("zone inconnue")
    w, h = await size(src)
    bw = max(8, min(int(w * w_pct / 100), w - 4))
    bh = max(8, min(int(h * h_pct / 100), h - 4))
    fx, fy = ZONES[zone]
    x = max(2, min(int((w - bw) * fx), w - bw - 2))
    y = max(2, min(int((h - bh) * fy), h - bh - 2))
    ctx.set(0.3, "effacement du filigrane…")
    await run_cmd(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vf", f"delogo=x={x}:y={y}:w={bw}:h={bh}",
                   "-frames:v", "1", str(dest)])


async def run(ctx: Ctx, p: dict) -> str:
    path = src_file(p)
    action = p.get("action", "upscale")
    out = output_dir("images")
    out.mkdir(parents=True, exist_ok=True)
    name = upload_name(path)
    if action == "upscale":
        factor = 4 if int(p.get("factor", 2)) == 4 else 2
        dest = unique(out, f"{name}.x{factor}", ".png")
        run_ = upscale(ctx, path, dest, factor, p.get("style", "photo"))
    elif action == "rembg":
        model = p.get("model") or cfg["images"]["rembg_model"]
        if model not in REMBG_MODELS:
            raise RuntimeError("modèle inconnu")
        dest = unique(out, f"{name}.sans-fond", ".png")
        run_ = rembg(ctx, path, dest, model)
    elif action == "watermark":
        try:
            wp, hp = (min(60.0, max(2.0, float(p.get(k, d)))) for k, d in (("w_pct", 25), ("h_pct", 14)))
        except (TypeError, ValueError):
            raise RuntimeError("paramètre invalide")
        dest = unique(out, f"{name}.sans-filigrane", ".png")
        run_ = watermark(ctx, path, dest, p.get("zone", "br"), wp, hp)
    else:
        raise RuntimeError("action inconnue")
    try:
        await run_
        if not dest.stat().st_size:
            raise RuntimeError("sortie vide")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    ctx.set(1.0, dest.name)
    return str(dest)


register("image", run, gpu=lambda p: p.get("action", "upscale") == "upscale", frees_vram=True)
