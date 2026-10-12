"""Windows entry point (PyInstaller exe): server in a thread + native WebView2 window, browser as fallback."""
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
        webview.create_window("Atelier", url, width=1280, height=840, min_size=(900, 600))
        webview.start()
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


def main() -> int:
    _log_streams()
    from .config import cfg
    port = int(cfg["server"]["port"])
    url = f"http://127.0.0.1:{port}/"
    if _up(port):  # already running: just show it
        webbrowser.open(url)
        return 0
    import uvicorn

    from .main import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, timeout_graceful_shutdown=3))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    if not _wait(port):
        print("serveur non démarré", file=sys.stderr)
        return 1
    if os.environ.get("ATELIER_NO_WINDOW") == "1":  # CI / service mode: serve until killed
        t.join()
    elif not _window(url):
        _quit_box(url)
    server.should_exit = True
    t.join(8)
    return 0
