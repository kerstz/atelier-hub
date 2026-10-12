"""Native window for Atelier (pywebview). Pure client: closing it never touches the service.

Exit codes: 0 normal, 2 pywebview/backend unusable (launcher falls back to a browser).
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
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
        try:  # GTK: ask the compositor for focus (window.native is the Gtk.ApplicationWindow)
            window.native.present()
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


def gtk_view(window):
    """The pywebview GTK BrowserView of `window` (window.native is only the Gtk.ApplicationWindow)."""
    from webview.platforms.gtk import BrowserView

    return BrowserView.instances.get(window.uid)


def recover_from_crashes(window, state: dict) -> None:
    """WebKit's render process can abort (seen on WebKitGTK 2.54 / Mesa): reload the page instead of leaving a
    dead window; after 3 crashes in 2 minutes give up with exit code 2 so the launcher opens a browser."""
    def hook() -> bool:
        try:
            view = gtk_view(window).webview
            from gi.repository import GLib
        except Exception as e:
            state["hook_error"] = repr(e)
            try:
                with open(runtime_dir() / "desktop.log", "a") as f:
                    f.write(f"{time.strftime('%F %T')} crash recovery NOT armed: {e!r}\n")
            except OSError:
                pass
            return False

        def log(msg: str) -> None:
            try:
                p = runtime_dir() / "desktop.log"
                with open(p, "a") as f:
                    f.write(f"{time.strftime('%F %T')} {msg}\n")
            except OSError:
                pass

        def on_crash(wv, reason=None, *_):
            now = time.monotonic()
            state["crashes"] = [t for t in state.get("crashes", []) if now - t < 120] + [now]
            log(f"web process terminated (reason={reason}), crash #{len(state['crashes'])}")
            if len(state["crashes"]) > 3:
                state["gave_up"] = True
                log("too many crashes: giving up (launcher falls back to a browser)")
                GLib.idle_add(window.destroy)
            else:
                # a plain reload() of a dead view can stay white: load the URL again on a fresh process
                target = wv.get_uri() or state.get("url") or "http://127.0.0.1:7777/"
                GLib.timeout_add(400, lambda: (wv.load_uri(target), log(f"reloaded {target}"), False)[-1])
            return False

        view.connect("web-process-terminated", on_crash)
        log("crash recovery armed")
        return False

    try:
        from gi.repository import GLib
        window.events.shown += lambda: GLib.idle_add(hook)
    except Exception:
        pass


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

    # Mesa + WebKitGTK >= 2.42: the DMABUF renderer is the usual cause of render-process aborts
    if os.environ.get("ATELIER_WEBKIT_SAFE", "1") != "0":
        os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
        # décodage logiciel: évite le chemin VA/GL de GStreamer dans le processus de rendu
        os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", "vah264dec:NONE,vah265dec:NONE,vavp9dec:NONE,vaav1dec:NONE")
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
    state: dict = {"url": a.url}
    if a.gui == "gtk":
        recover_from_crashes(window, state)
    try:
        serve(sp, window, webview)
        webview.start(gui=a.gui, icon=str(ICON) if ICON.is_file() else None)
    except Exception as e:
        print(f"fenêtre impossible: {e}", file=sys.stderr)
        return 2
    finally:
        sp.unlink(missing_ok=True)
    return 2 if state.get("gave_up") else 0


if __name__ == "__main__":
    raise SystemExit(main())
