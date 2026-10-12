# Contributing to Atelier

Thanks for considering a contribution! Atelier is a small, opinionated project: a local hub that **wraps
existing tools** rather than reimplementing them.

## Setup

```bash
git clone https://github.com/kerstz/atelier-hub && cd atelier-hub
uv sync --frozen
uv run python -m atelier           # http://127.0.0.1:7777
```

Optional tools (ffmpeg, whisper.cpp, Ollama, …) are only needed for the features that use them; the
**System → Dependencies** panel lists what is missing and how to install it.

## Ground rules

- **Stack is fixed**: Python 3.12 + FastAPI, SQLite, static HTML + vanilla JS + one CSS file. No build step,
  no CDN, no frontend framework.
- **Wrap, don't reimplement**: call the CLI through `proc.run_cmd` (argument lists, never a shell).
- **Small files, few comments**: comment only what is non-obvious; no docstring boilerplate.
- **Offline first**: nothing is downloaded or installed implicitly; anything that downloads must be listed and
  confirmed first.
- **Security**: paths from the UI must be resolved and confined (see `util.upload_paths`); user text never goes
  into a shell command.
- **UI strings**: French is the source language. Add an entry to `static/i18n.en.js` for every new string —
  `scripts/smoke19.sh` fails when a static string has no English translation.

## Tests

There is no test framework by design. Each feature area has a smoke script in `scripts/` that runs offline
with fakes where models are involved:

```bash
bash scripts/smoke-all.sh --quick      # everything except network/long runs
bash scripts/smoke20.sh                # one area
```

Add or extend the smoke script of the area you touch; keep it runnable without models.

## Pull requests

1. Branch from `main`, keep the change focused.
2. Run `bash scripts/smoke-all.sh --quick` and say so in the PR.
3. For UI changes, include a screenshot (dark theme, English).
4. Describe the *why*; link an issue if there is one.

By contributing you agree that your contribution is licensed under the MIT License.
