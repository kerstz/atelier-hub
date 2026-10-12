"""PyInstaller entry point. Windows: server in a thread + WebView2 window (browser fallback). Linux (.deb): server + browser."""
import os
import socket
import sys
import threading
import time
import webbrowser

from . import plat


def _log_streams() -> None:
    # windowed exe: sys.stdout/stderr are None and uvicorn's logging would crash on them
    if sys.stdout is None or sys.stderr is None:
        d = plat.config_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = open(d / "atelier.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _up(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), 0.4).close()
        return True
    except OSError:
        return False


def _wait(port: int, secs: float = 30) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if _up(port):
            return True
        time.sleep(0.2)
    return False


def _window(url: str) -> bool:
    """Blocks until the window is closed. False if no web view is usable."""
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window("Atelier", url, width=1280, height=840, min_size=(900, 600))
        webview.start(private_mode=False)
        return True
    except Exception as e:
        print(f"pywebview indisponible: {e}", file=sys.stderr)
        return False


def _quit_box(url: str) -> None:
    webbrowser.open(url)
    try:
        import tkinter as tk
        r = tk.Tk()
        r.title("Atelier")
        tk.Label(r, text=f"Atelier tourne sur {url}", padx=24, pady=12).pack()
        tk.Button(r, text="Quitter", command=r.destroy, padx=16).pack(pady=(0, 14))
        r.mainloop()
    except Exception:
        threading.Event().wait()


def _cli(argv: list[str]) -> int | None:
    """Helper modes of the same exe (a windowed exe has no console: results go to a file or a pipe)."""
    if argv[:1] == ["--winaudio"]:
        from . import winaudio
        return winaudio.main(argv[1:])
    if argv[:1] == ["--hw-models"] and len(argv) > 1:  # Atelier.exe --hw-models out.txt: models recommended for this PC
        from . import hw, tiers
        models = sorted({m for m in tiers.recommend(hw.profile())["models"].values() if m})
        open(argv[1], "w", encoding="utf-8").write("\n".join(models) + "\n")
        return 0
    if argv[:1] == ["--check-imports"] and len(argv) > 1:  # CI: optional/lazy modules really are in the bundle
        import importlib
        mods = ["ctranslate2", "sentencepiece", "docx", "pptx", "openpyxl", "lxml.etree", "httpx", "certifi", "atelier.main"]
        mods += ["webview", "sounddevice", "tkinter"] if plat.NT else []
        bad = []
        for m in mods:
            try:
                importlib.import_module(m)
            except Exception as e:
                bad.append(f"{m}: {e}")
        open(argv[1], "w", encoding="utf-8").write("\n".join(bad or ["ok"]) + "\n")
        return 1 if bad else 0
    return None


def main() -> int:
    rc = _cli(sys.argv[1:])
    if rc is not None:
        return rc
    _log_streams()
    if not plat.NT:  # frozen Linux: the bootloader's LD_LIBRARY_PATH would break system ffmpeg/yt-dlp children
        orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
        os.environ.pop("LD_LIBRARY_PATH", None)
        if orig:
            os.environ["LD_LIBRARY_PATH"] = orig
        local_bin = os.path.expanduser("~/.local/bin")  # uv/pipx tools; absent from systemd --user's PATH
        if local_bin not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = os.environ.get("PATH", "/usr/bin:/bin") + os.pathsep + local_bin
    from .config import cfg
    port = int(cfg["server"]["port"])
    url = f"http://127.0.0.1:{port}/"
    if _up(port):  # already running: just show it
        webbrowser.open(url)
        return 0
    import uvicorn

    from .main import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, timeout_graceful_shutdown=3))
    if not plat.NT:  # uvicorn in a thread sets no signal handler: without this, systemd stop skips job cleanup
        import signal
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: setattr(server, "should_exit", True))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    if not _wait(port):
        print("serveur non démarré", file=sys.stderr)
        return 1
    if os.environ.get("ATELIER_NO_WINDOW") == "1":  # CI / service mode: serve until killed
        t.join()
    elif not plat.NT:
        webbrowser.open(url)
        t.join()
    elif not _window(url):
        _quit_box(url)
    server.should_exit = True
    t.join(8)
    return 0
