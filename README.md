# Atelier

[Français](README.fr.md) · English

A local, offline-first, all-in-one web hub for translation, media and documents. One small FastAPI
service bound to `127.0.0.1:7777`, a vanilla HTML/JS UI (no build step, no CDN), and a job queue that
wraps battle-tested CLIs instead of reimplementing them.

Built and tested on **CachyOS / Arch Linux** with an AMD GPU (RX 6900 XT, Vulkan). The UI is in French by
default and can be switched to English from the sidebar.

## What it does

| Tab | Features |
|---|---|
| **Translate** | Free text, paragraph chunking with cross-block context, streaming output, glossaries, image → text → translation (vision model), dictation (microphone → whisper.cpp), read aloud / export MP3 (Piper) |
| **YouTube** | Video or playlist → mkv / mp3 / subtitles only, quality choice, real progress |
| **Subtitles** | URL or local media/SRT → existing subtitles, else whisper.cpp → translated SRT (+ optional soft-sub mkv), transcript summary with timestamped chapters |
| **Documents** | PDF (pdf2zh-next, mono + bilingual, auto OCR for scans), DOCX / PPTX / XLSX with inline formatting kept, EPUB (TOC + metadata kept) |
| **Convert** | Video/audio (ffmpeg, VAAPI h264/hevc, AV1 on CPU), images (libvips), documents (pandoc + LibreOffice), e-books (calibre), batch + zip |
| **Images** | Upscale ×2 / ×4 (Real-ESRGAN, Vulkan), background removal (rembg) |
| **Audio** | Stem separation (Demucs), voice denoising (DeepFilterNet) |
| **Services** | Probe, start and stop your other local services (Open WebUI, Jellyfin, …) |
| **System** | VRAM, loaded Ollama models, dependency check, disk usage and cleanup |

Plus: a global GPU lock (one GPU job at a time, models unloaded before non-Ollama GPU jobs), job
queue with SSE progress, cancel, retry, per-job logs, desktop notifications, and an optional native
window (pywebview) with a menu entry.

35 languages, including variants with an explanation (Portuguese PT/BR, Chinese simplified/traditional,
Filipino vs Cebuano, Indonesian vs Malay…).

## Requirements

- Linux with systemd (user units), Python 3.12 + [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) with a translation model (default `translategemma:12b`) and a second
  model (default `gemma3:12b`, summaries and image translation)
- `ffmpeg`, `yt-dlp`; whisper.cpp built with Vulkan (`scripts/build-whisper.sh`)
- Per feature (the **System → Dependencies** panel tells you what is missing and how to install it):
  `pdf2zh-next`, `ocrmypdf` + `tesseract`, `pandoc`, LibreOffice, `calibre`, `libvips`, `piper-tts`,
  `rembg`, `realesrgan-ncnn-vulkan`, `demucs`, `deep-filter`

Nothing is downloaded or installed by Atelier itself.

## Install

```bash
git clone https://github.com/kerstz/atelier-hub && cd atelier-hub
./install.sh --dry-run             # print the plan for your distro, change nothing
./install.sh                       # standard tier (asks before doing anything)
```

`install.sh` detects Arch/CachyOS/Manjaro (pacman), Debian/Ubuntu/Mint (apt), Fedora/Nobara (dnf) and
openSUSE (zypper). Options: `--tier=minimal|standard|full`, `--yes`, `--dry-run`, `--no-whisper`,
`--no-desktop`, `--no-service`, `--ollama`, `--models` (pulls the Ollama models recommended for *your* hardware),
`--engine=ct2` (CPU translation for small machines).

| Tier | Adds |
|---|---|
| `minimal` | ffmpeg, yt-dlp, poppler, uv, the service — translate, YouTube, subtitles with existing captions |
| `standard` (default) | OCR, pandoc, LibreOffice, libvips, whisper.cpp (Vulkan build), pdf2zh-next, desktop entry |
| `full` | calibre, Piper, rembg, Demucs, Real-ESRGAN, DeepFilterNet |

Manual route (any distro): `bash scripts/env-check.sh`, `uv sync --frozen`, `bash scripts/install-service.sh`,
optionally `bash scripts/install-desktop.sh`.

Open <http://127.0.0.1:7777>. Settings live in `config.toml` (models, paths, ports, voices, limits).

## Hardware adaptation

Atelier profiles the machine (GPU VRAM — AMD/NVIDIA —, RAM, cores, AVX2) and picks models per role:
16 GB+ GPU → `translategemma:12b` / `gemma3:12b`; 8 GB → the 4B variants; no usable GPU → **NLLB-200 on
CPU** (CTranslate2, int8, 35 languages) so a small PC can still translate text, subtitles, DOCX/PPTX/XLSX and
EPUB (PDF needs Ollama). See **System → Hardware**, `python -m atelier.hw`, and `[translate] engine` in
`config.toml` (`auto` only ever picks what is already installed). NLLB weights are CC-BY-NC.

## Tests

There is no test framework, only one smoke script per phase:

```bash
bash scripts/smoke-all.sh --quick    # everything except network/long ones (3, 4, 5)
bash scripts/smoke-all.sh            # full run (needs Ollama, whisper.cpp, network)
```

## Layout

```
atelier/    FastAPI backend (jobs, SQLite, one module per feature)
static/     UI: index.html, one JS file per tab, one CSS file
scripts/    service/desktop install, env check, smoke tests
systemd/    user unit template
desktop/    .desktop template
```

## Security model

Single-user, local only: binds to loopback, rejects foreign `Host`/`Origin` headers (same origin only),
never builds shell commands from UI input, keeps writes inside `~/Atelier` and the data directory.
Do not expose it to a network.

## License

Not specified yet.
