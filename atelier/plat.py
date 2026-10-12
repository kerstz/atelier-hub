"""Platform layer: everything that differs between Linux and Windows lives here.
ATELIER_FAKE_WIN=1 flips argv/kwargs decisions on Linux for tests (real Windows APIs stay guarded by os.name)."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

NT = os.name == "nt"
IS_WIN = NT or os.environ.get("ATELIER_FAKE_WIN") == "1"
FROZEN = bool(getattr(sys, "frozen", False))
CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x200, 0x08000000


def spawn_kw() -> dict:
    """Extra create_subprocess_exec kwargs: own process group (Linux) / own group, no console (Windows)."""
    if IS_WIN:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}
    return {"start_new_session": True}


def run_kw() -> dict:
    """subprocess.run/Popen kwargs: no console window flash from the windowed exe."""
    return {"creationflags": CREATE_NO_WINDOW} if NT else {}


def kill_tree(proc, force: bool = False) -> None:
    """Kill a child and its descendants. Never raises on an already-dead process."""
    if proc is None or proc.returncode is not None:
        return
    if NT:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass


def open_folder_argv(folder: str) -> list[str]:
    return ["explorer", folder] if IS_WIN else ["xdg-open", folder]


def open_folder(folder: str) -> None:
    if NT:
        os.startfile(folder)  # noqa: S606 — local path already checked against the output dir
        return
    subprocess.Popen(open_folder_argv(folder), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def distro() -> str:
    """windows | arch | debian | fedora | unknown — which install commands the UI shows."""
    if IS_WIN:
        return "windows"
    from .maint import distro_family
    return distro_family(os.environ.get("ATELIER_OS_RELEASE", "/etc/os-release"))


# Arch package -> winget id ("" = no winget package)
WINGET = {"ffmpeg": "Gyan.FFmpeg", "yt-dlp": "yt-dlp.yt-dlp", "poppler": "oschwartz10612.Poppler", "pandoc-cli": "JohnMacFarlane.Pandoc",
          "libreoffice-fresh": "TheDocumentFoundation.LibreOffice", "calibre": "calibre.calibre",
          "tesseract": "UB-Mannheim.TesseractOCR", "ollama": "Ollama.Ollama"}
OLLAMA_INSTALL = "curl -fsSL https://ollama.com/install.sh | sh"


def _pkg_cmd(hint: str) -> str:
    """'sudo pacman -S a b' -> the same install for this OS."""
    d = distro()
    if d == "windows":
        ids = [WINGET.get(p, "") for p in hint.split()[3:] if not p.startswith("tesseract-data-")]
        if not ids or not all(ids):
            return "installateur Windows : voir la page du projet"
        return " ; ".join(f"winget install {i}" for i in dict.fromkeys(ids))
    from .maint import _linux_hint
    return _linux_hint(hint, d)


def ollama_hint() -> str:
    """How to get Ollama answering on this machine (installed but stopped, or not installed)."""
    have = bool(shutil.which("ollama"))
    d = distro()
    if d == "windows":
        return "lancer Ollama (menu Démarrer)" if have else "winget install Ollama.Ollama"
    if have:
        return "sudo systemctl start ollama"
    return "sudo pacman -S ollama && sudo systemctl enable --now ollama" if d == "arch" else OLLAMA_INSTALL


TOOL_HINT = {"ffmpeg": "sudo pacman -S ffmpeg", "ffprobe": "sudo pacman -S ffmpeg", "yt-dlp": "sudo pacman -S yt-dlp",
             "pandoc": "sudo pacman -S pandoc-cli", "soffice": "sudo pacman -S libreoffice-fresh",
             "ebook-convert": "sudo pacman -S calibre", "pdftotext": "sudo pacman -S poppler", "tesseract": "sudo pacman -S tesseract",
             "whisper-cli": "scripts/build-whisper.sh", "ollama": "", "mpv": "sudo pacman -S mpv"}


def missing_tool(e: OSError) -> str:
    """FileNotFoundError from spawning a CLI -> 'X n'est pas installé : <how>' (never a raw errno/path).
    "" when it is not about a program (a missing data file keeps its own message)."""
    raw = str(e.filename or "")
    name = Path(raw).name
    stem = name[:-4] if name.lower().endswith(".exe") else name
    if not raw:
        return "Un outil nécessaire est introuvable : voir Système › Dépendances." if NT else ""
    if stem not in TOOL_HINT and ("/" in raw or "\\" in raw or "." in stem):
        return ""
    hint = ollama_hint() if stem == "ollama" else TOOL_HINT.get(stem, "")
    return localize(f"{stem} n'est pas installé" + (f" : {hint}" if hint else " (voir Système › Dépendances)"))


def localize(msg: str) -> str:
    """User-facing text: package/script commands rewritten for this OS (apt on Debian/Ubuntu, winget/.ps1 on Windows)."""
    msg = re.sub(r"sudo pacman -S [\w.+-]+(?: [\w.+-]+)*", lambda m: _pkg_cmd(m.group(0)), msg)
    if msg.startswith("Ollama injoignable") and " — " not in msg:
        msg += f" — {ollama_hint()}"
    if not IS_WIN:
        if FROZEN:  # .deb ships the standalone setup scripts in /opt/atelier/scripts (scripts/build-deb.sh)
            def sh(m):
                f = Path(sys.executable).parent / "scripts" / m.group(1)
                return f"bash {f}{m.group(2)}" if f.is_file() else "voir la page du projet (README, section outils)"
            msg = re.sub(r"scripts/([\w-]+\.sh)((?: [\w=-]+)*)", sh, msg)
        return msg
    base = str(Path(sys.executable).parent) + "\\" if FROZEN else ""
    run = 'powershell -ExecutionPolicy Bypass -File ' if FROZEN else ""

    def one(m):
        path = base + "scripts\\" + m.group(1).replace("build-whisper", "win-setup") + ".ps1"
        return f'{run}"{path}"' if FROZEN else path
    return re.sub(r"scripts/([\w-]+)\.sh", one, msg)


def audio_cmd() -> list[str]:
    """argv prefix of the PortAudio helper (atelier/winaudio.py): the exe itself when frozen."""
    if FROZEN:
        return [sys.executable, "--winaudio"]
    return [sys.executable, str(Path(__file__).with_name("winaudio.py"))]


def toast_argv(title: str, body: str) -> tuple[list[str], dict]:
    """PowerShell toast (no module needed). Text goes through the environment: no quoting/injection issue."""
    ps = r"""
$null=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
$null=[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]
$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1)
$t=$x.GetElementsByTagName('text')
$null=$t.Item(0).AppendChild($x.CreateTextNode($env:ATELIER_T))
$null=$t.Item(1).AppendChild($x.CreateTextNode($env:ATELIER_B))
$app='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], {"ATELIER_T": title, "ATELIER_B": body}


def venv_python(venv: str) -> str:
    return f"{venv}/Scripts/python.exe" if IS_WIN else f"{venv}/bin/python"


# Linux default location -> Windows location (applied to every string setting; only the prefix changes)
WIN_PATHS = (("~/.local/share/atelier", "~/AppData/Local/Atelier"), ("~/.local/share/piper", "~/AppData/Local/Atelier/piper"),
             ("~/.local/opt", "~/AppData/Local/Atelier/opt"), ("/dev/dri/renderD128", ""))


def remap(value, table=WIN_PATHS):
    if isinstance(value, dict):
        return {k: remap(v, table) for k, v in value.items()}
    if isinstance(value, str):
        for old, new in table:
            if value == old or value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def config_dir() -> Path:
    base = os.environ.get("APPDATA") if NT else None
    return Path(base or Path.home() / ".config") / "Atelier"


# Where Windows installers put the tools Atelier wraps (appended to PATH at startup, after the user's own PATH)
WIN_DIRS = (r"%ProgramFiles%\LibreOffice\program", r"%ProgramFiles%\Calibre2", r"%ProgramFiles%\Tesseract-OCR",
            r"%ProgramFiles%\Pandoc", r"%LOCALAPPDATA%\Pandoc", r"%LOCALAPPDATA%\Programs\Ollama",
            r"%LOCALAPPDATA%\Microsoft\WinGet\Links", r"%USERPROFILE%\.local\bin", r"%ProgramFiles%\mpv",
            r"%LOCALAPPDATA%\Atelier\bin")


def path_candidates() -> list[str]:
    dirs = list(WIN_DIRS)
    base = os.path.expandvars(r"%LOCALAPPDATA%\Atelier\opt")
    if os.path.isdir(base):
        for d in sorted(os.listdir(base)):
            dirs += [os.path.join(base, d), os.path.join(base, d, "bin")]
    return [os.path.expandvars(d) for d in dirs]


def _registry_path() -> list[str]:
    out: list[str] = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    out += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(os.pathsep)
            except OSError:
                pass
    except ImportError:
        pass
    return out


def extend_path() -> None:
    """Make freshly installed tools visible (winget edits the registry PATH, not our inherited one)."""
    if not NT:
        return
    cur = os.environ.get("PATH", "").split(os.pathsep)
    add = [d for d in dict.fromkeys(_registry_path() + path_candidates()) if d and d not in cur and os.path.isdir(d)]
    os.environ["PATH"] = os.pathsep.join(cur + add)


def force_utf8() -> None:
    """Windows opens text files in the ANSI code page by default; every file we write or read is UTF-8."""
    import builtins
    import io
    if not NT:
        return
    os.environ.setdefault("PYTHONUTF8", "1")  # python CLIs we spawn (piper, ocrmypdf, demucs)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if sys.flags.utf8_mode or getattr(builtins.open, "_atelier", False):
        return
    real = io.open

    def utf8_open(file, mode="r", buffering=-1, encoding=None, *a, **k):
        if encoding is None and "b" not in mode:
            encoding = "utf-8"
        return real(file, mode, buffering, encoding, *a, **k)
    utf8_open._atelier = True
    builtins.open = io.open = utf8_open


# ---- hardware (Windows) ---------------------------------------------------------------------------

_PS_GPU = r"""
$k='HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*'
$cards=@(Get-ItemProperty $k -ErrorAction SilentlyContinue | Where-Object {$_.'HardwareInformation.qwMemorySize'} | ForEach-Object {
  [pscustomobject]@{name=$_.DriverDesc; total=[uint64]$_.'HardwareInformation.qwMemorySize'; dev=$_.MatchingDeviceId}})
$used=0
try { $used=[uint64](Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop).CounterSamples |
  Measure-Object CookedValue -Maximum | ForEach-Object {$_.Maximum} } catch {}
[pscustomobject]@{cards=$cards; used=$used} | ConvertTo-Json -Compress -Depth 4
"""
_VEN = {"1002": "amd", "10de": "nvidia", "8086": "intel"}
_gpu_cache: tuple[float, list[dict]] = (0.0, [])


def win_gpus(ttl: float = 5.0) -> list[dict]:
    """[{vendor, card, total, used}] from the registry + perf counters. Approximate: `used` is the busiest adapter's
    dedicated usage, attributed to the largest card. Cached: PowerShell costs ~0.5 s."""
    global _gpu_cache
    if time.monotonic() - _gpu_cache[0] < ttl:
        return _gpu_cache[1]
    out: list[dict] = []
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        try:
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", _PS_GPU], capture_output=True, text=True,
                               timeout=15, creationflags=CREATE_NO_WINDOW if NT else 0)
            out = parse_win_gpus(r.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    _gpu_cache = (time.monotonic(), out)
    return out


def parse_win_gpus(raw: str) -> list[dict]:
    try:
        d = json.loads(raw)
    except ValueError:
        return []
    cards = d.get("cards") or []
    if isinstance(cards, dict):
        cards = [cards]
    out = []
    for c in cards:
        dev = str(c.get("dev") or "").upper()
        ven = dev.split("VEN_")[1][:4].lower() if "VEN_" in dev else ""
        out.append({"vendor": _VEN.get(ven, "other"), "card": c.get("name") or "gpu", "total": int(c.get("total") or 0), "used": 0})
    if out:
        max(out, key=lambda g: g["total"])["used"] = min(int(d.get("used") or 0), max(g["total"] for g in out))
    return out


def win_mem() -> tuple[int, int]:
    """(total, available) bytes via GlobalMemoryStatusEx."""
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong)]
    m = MS()
    m.l = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.tot), int(m.avail)


def win_cpu_flags() -> set[str]:
    import ctypes
    f = ctypes.windll.kernel32.IsProcessorFeaturePresent
    return {n for n, pf in (("avx2", 40), ("avx512f", 41)) if f(pf)}
