import re
import time
from contextvars import ContextVar
from pathlib import Path

from .config import data_dir

JOB: ContextVar[int | None] = ContextVar("atelier_job", default=None)
CAP = 2_000_000
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def path(jid: int) -> Path:
    return data_dir() / "logs" / f"{jid}.log"


class Log:
    """Append-only per-job command log, capped. Opened per run_cmd call, bound to the running job."""

    def __init__(self, jid: int):
        p = path(jid)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.size = p.stat().st_size if p.exists() else 0
        self.truncated = False
        self.f = open(p, "a", encoding="utf-8", errors="replace")

    def write(self, line: str) -> None:
        line = ANSI_RE.sub("", line)
        if self.size + len(line) + 1 > CAP:
            self.truncated = True
            return
        self.f.write(line + "\n")
        self.size += len(line) + 1

    def close(self, tail: list[str] | None = None) -> None:
        if self.truncated:
            self.f.write("… journal tronqué (limite atteinte), dernières lignes :\n")
            for line in tail or []:
                self.f.write(ANSI_RE.sub("", line)[:500] + "\n")
        self.f.close()


def open_current() -> Log | None:
    jid = JOB.get()
    return Log(jid) if jid is not None else None


def append(jid: int, text: str) -> None:
    try:
        with open(path(jid), "a", encoding="utf-8", errors="replace") as f:
            f.write(text.rstrip("\n") + "\n")
    except OSError:
        pass


def read(jid: int, tail: int = 300_000) -> str | None:
    p = path(jid)
    if not p.is_file():
        return None
    data = p.read_bytes()
    cut = len(data) > tail
    text = data[-tail:].decode("utf-8", errors="replace")
    return ("… début coupé …\n" if cut else "") + text


def remove(ids: list[int]) -> None:
    for i in ids:
        path(i).unlink(missing_ok=True)


def purge(days: int = 14) -> None:
    d = data_dir() / "logs"
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file() and time.time() - f.stat().st_mtime > days * 86400:
                f.unlink(missing_ok=True)
