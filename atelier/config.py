import os
import sys
import tomllib
from pathlib import Path

from . import plat

ROOT = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent.parent)

DEFAULTS = {
    "server": {"port": 7777, "max_upload_mb": 16384, "min_free_gb": 2},
    "paths": {"output": "~/Atelier", "data": "~/.local/share/atelier"},
    "gpu": {"card": "auto", "free_vram": True},
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "translate_model": "translategemma:12b",
        "second_model": "gemma3:12b",
        "vision_model": "gemma3:12b",
        "timeout": 300,
    },
    "summary": {"model": "", "num_ctx": 8192, "lang": "fr"},
    "translate": {"chunk_chars": 2500, "context": True, "engine": "auto"},
    "ctranslate2": {"model_dir": "~/.local/share/atelier/nllb-200-distilled-600M-int8", "threads": 0},
    "whisper": {
        "bin": "whisper-cli",
        "model": "~/.local/opt/whisper.cpp/models/ggml-large-v3-turbo.bin",
        "threads": 8,
    },
    "subtitles": {"batch": 40, "num_ctx": 8192, "use_auto_captions": False},
    "docs": {
        "pdf_model": "", "qps": 2, "auto_glossary": False,
        "ocr_bin": "ocrmypdf", "ocr_langs": "fra+eng", "ocr_jobs": 4,
    },
    "tts": {"bin": "piper", "voices_dir": "~/.local/share/piper"},
    "images": {"realesrgan_bin": "realesrgan-ncnn-vulkan", "models_dir": "", "gpu_id": 0, "rembg_bin": "rembg", "rembg_model": "u2net"},
    "audio": {"demucs_bin": "demucs", "demucs_device": "auto", "deepfilter_bin": "deep-filter"},
    "voice": {
        "engine": "auto",
        "python": plat.venv_python("~/.local/share/atelier/seedvc-venv"),
        "seedvc_dir": "~/.local/opt/seed-vc",
        "voices_dir": "~/.local/share/atelier/voices",
        "live_block": 0.18, "live_steps": 6, "live_cfg": 0.0, "live_gate_db": -50.0, "live_max_minutes": 120,
        "live_extra_right": 0.02, "live_checkpoint": "", "live_config": "",
        "file_steps": 30, "offline": True,
    },
    "player": {"transcode": "auto", "cache_days": 7, "cache_max_gb": 5, "safe_gst": True, "mpv_bin": "mpv"},
    "desktop": {"notify": True, "notify_min_seconds": 5},
    "convert": {"vaapi_device": "/dev/dri/renderD128", "jobs": 2},
    "grammar": {"lt_port": 8081, "lt_cmd": "", "lt_idle_min": 10, "lt_heap_mb": 1024, "en_dialect": "American"},
    "youtube": {"sub_langs": "en", "cookies_from_browser": "", "rate_limit": ""},
}


def _load() -> dict:
    path = Path(os.environ.get("ATELIER_CONFIG", ROOT / "config.toml"))
    if "ATELIER_CONFIG" not in os.environ and (plat.IS_WIN or plat.FROZEN) and (plat.config_dir() / "config.toml").exists():
        path = plat.config_dir() / "config.toml"
    user = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = {k: {**v, **user.get(k, {})} for k, v in DEFAULTS.items()} | {
        k: v for k, v in user.items() if k not in DEFAULTS
    }
    return plat.remap(out) if plat.IS_WIN else out


if plat.NT:
    plat.force_utf8()
    plat.extend_path()

cfg = _load()


def output_dir(kind: str | None = None) -> Path:
    base = Path(cfg["paths"]["output"]).expanduser()
    return base / kind if kind else base


def data_dir() -> Path:
    return Path(cfg["paths"]["data"]).expanduser()
