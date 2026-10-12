"""Native window for Atelier (pywebview). Pure client: closing it never touches the service.

Exit codes: 0 normal, 2 pywebview/backend unusable (launcher falls back to a browser).
"""
import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path

NAME = "atelier"
MIN_SIZE = (900, 600)
DEFAULT_SIZE = (1280, 820)
ICON = Path(__file__).resolve().parent.parent / "static" / "icon.svg"


def runtime_dir() -> Path:
    """Private dir for the control socket (same rule as the launcher): never a shared /tmp."""
    d = os.environ.get("XDG_RUNTIME_DIR")
    if d:
        return Path(d)
    p = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / NAME
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def sock_path() -> Path:
    return runtime_dir() / "atelier-desktop.sock"


def state_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / NAME / "window.json"


def load_state() -> dict:
    try:
        d = json.loads(state_path().read_text())
        w, h = int(d["width"]), int(d["height"])
        out = {"width": max(w, MIN_SIZE[0]), "height": max(h, MIN_SIZE[1])}
        if "x" in d and "y" in d:
            out |= {"x": int(d["x"]), "y": int(d["y"])}
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}


class Saver:
    def __init__(self, state: dict):
        self.state, self.timer = dict(state), None

    def update(self, **kw) -> None:
        self.state.update(kw)
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(0.5, self.flush)
        self.timer.start()

    def flush(self) -> None:
        try:
            p = state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.state))
        except OSError:
            pass


def alive(path: Path) -> bool:
    s = socket.socket(socket.AF_UNIX)
    try:
        s.settimeout(1)
        s.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        s.close()


def serve(path: Path, window, webview) -> None:
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(4)

    def present() -> None:
        try:
            window.restore()
            window.show()
        except Exception:
            pass
        try:  # GTK: ask the compositor for focus
            window.native.window.present()
        except Exception:
            pass

    def loop() -> None:
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(2)
                    data = conn.makefile("r", encoding="utf-8", errors="replace").readline().strip()
                cmd, _, arg = data.partition(" ")
                if cmd == "open" and arg:
                    window.evaluate_js(f"location.hash = {json.dumps(arg)}")
                if cmd in ("open", "focus"):
                    present()
            except Exception:
                continue  # a bad client must never kill the control thread

    threading.Thread(target=loop, daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7777/")
    ap.add_argument("--hash", default="")
    ap.add_argument("--gui", choices=["gtk", "qt"], default="gtk")
    a = ap.parse_args()

    sp = sock_path()
    if sp.exists():
        if alive(sp):
            return 0
        sp.unlink(missing_ok=True)

    sys.argv[0] = NAME  # Qt app_id / GTK program name -> window class "atelier"
    try:
        if a.gui == "gtk":
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib

            GLib.set_prgname(NAME)
            GLib.set_application_name("Atelier")
        import webview
    except Exception as e:
        print(f"pywebview indisponible: {e}", file=sys.stderr)
        return 2

    st = load_state()
    saver = Saver(st)
    url = a.url + (f"#{a.hash}" if a.hash else "")
    kw = {k: st[k] for k in ("x", "y") if k in st}
    window = webview.create_window("Atelier", url, width=st["width"], height=st["height"], min_size=MIN_SIZE, **kw)
    window.events.resized += lambda w, h: saver.update(width=w, height=h)
    window.events.moved += lambda x, y: saver.update(x=x, y=y)
    window.events.closing += lambda: saver.flush()
    try:
        serve(sp, window, webview)
        webview.start(gui=a.gui, icon=str(ICON) if ICON.is_file() else None)
    except Exception as e:
        print(f"fenêtre impossible: {e}", file=sys.stderr)
        return 2
    finally:
        sp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
