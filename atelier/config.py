import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "server": {"port": 7777},
    "paths": {"output": "~/Atelier", "data": "~/.local/share/atelier"},
    "gpu": {"card": "auto", "free_vram": True},
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "translate_model": "translategemma:12b",
        "second_model": "gemma3:12b",
        "vision_model": "gemma3:12b",
    },
    "summary": {"model": "", "num_ctx": 8192, "lang": "fr"},
    "translate": {"chunk_chars": 2500},
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
    "desktop": {"notify": True, "notify_min_seconds": 5},
    "convert": {"vaapi_device": "/dev/dri/renderD128", "jobs": 2},
    "youtube": {"sub_langs": "en", "cookies_from_browser": "", "rate_limit": ""},
}


def _load() -> dict:
    path = Path(os.environ.get("ATELIER_CONFIG", ROOT / "config.toml"))
    user = tomllib.loads(path.read_text()) if path.exists() else {}
    return {k: {**v, **user.get(k, {})} for k, v in DEFAULTS.items()} | {
        k: v for k, v in user.items() if k not in DEFAULTS
    }


cfg = _load()


def output_dir(kind: str | None = None) -> Path:
    base = Path(cfg["paths"]["output"]).expanduser()
    return base / kind if kind else base


def data_dir() -> Path:
    return Path(cfg["paths"]["data"]).expanduser()
