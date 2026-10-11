# Atelier

Local all-in-one web hub. Offline after setup. Bind 127.0.0.1:7777 only.

## Machine
CachyOS/Arch. User shell fish: scripts = bash shebang, cmds given to user = fish-compatible.
Ryzen 9 5900X, RX 6900 XT 16GB (RDNA2), 32GB RAM. VRAM shared with desktop.

## Rules (strict)
- Caveman replies. No preamble/recap/explain. Done = "ok" + cmds user must run.
- Grep before Read. Never re-read file just written.
- Noisy cmds: quiet flags + `2>&1 | tail -15`.
- Never run model downloads / long builds: print cmd, user runs.
- No subagents. No test framework: one scripts/smoke.sh per phase.
- Small files, no docstrings, comments only if non-obvious. Code quality normal.
- Ask nothing unless blocking: pick default, log in PROGRESS.md.
- One phase per session. End: update PROGRESS.md (≤15 lines: done/decisions/env/next), STOP.
- User later says only "phase N".

## Stack (fixed)
Python 3.12 + uv, FastAPI + uvicorn, SQLite (jobs). UI: static HTML + vanilla JS + 1 CSS, no build, no CDN. UI language French.
Backend wraps CLIs via async subprocess, never reimplement.
Global GPU lock: one GPU job at a time. Jobs: queue, SSE progress, cancel, history, open folder.
Outputs ~/Atelier/{youtube,subs,docs}. Settings in config.toml.
systemd --user unit for autostart.

## Engines
- LLM: Ollama (GPU via vulkan or rocm pkg; `ollama ps` must show GPU). Translate: TranslateGemma 12B (fallback gemma3:12b), official prompt format. 2nd model configurable.
- STT: whisper.cpp Vulkan, large-v3-turbo.
- yt-dlp + ffmpeg system pkgs.
- PDF: pdf2zh-next (BabelDOC) via `uv tool`, engine Ollama.

## Phases
1. Skeleton: env-check, shell + tabs, jobs + SSE, GPU lock, systemd unit. Tab Système: VRAM (amdgpu sysfs), Ollama loaded models + Décharger (keep_alive=0).
2. Traduire: panes, lang pickers, streaming, copy, paragraph chunking, glossary "a=b", history last 20.
3. YouTube: URL video/playlist; modes mkv best / mp3 / subs only; quality; parse `--newline` progress; clean filenames.
4. Sous-titres: URL or local av/SRT. yt-dlp en subs → else whisper.cpp → SRT → translate. SRT parsed/rebuilt in Python; LLM sees numbered lines only, batches ~40 + prev batch ctx; validate count, retry. Out .fr.srt + optional mkv soft-sub mux.
5. Documents: drag&drop. PDF → pdf2zh-next (mono + bilingual). DOCX/PPTX/XLSX → python-docx/pptx/openpyxl per paragraph/cell, keep format best-effort.
6. Services: dashboard from config.toml (Open WebUI :3000, Pinchflat :8945, Jellyfin :8096, Immich, Stirling-PDF): port probe, start/stop (systemctl --user / docker compose), open link. Never install.
