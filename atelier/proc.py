import asyncio
import os
import re
import signal
from collections import deque
import shlex
from typing import Callable

from . import joblog


class CmdError(RuntimeError):
    def __init__(self, msg: str, rc: int):
        super().__init__(msg)
        self.rc = rc


def _killpg(proc: asyncio.subprocess.Process, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _emit(raw: bytes, tail: deque, on_line, log=None) -> None:
    line = raw.decode(errors="replace").rstrip()
    if not line:
        return
    tail.append(line)
    if log:
        log.write(line)
    if on_line:
        on_line(line)


async def run_cmd(argv: list[str], on_line: Callable[[str], None] | None = None, **kw) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
        limit=1 << 20,
        **kw,
    )
    tail: deque[str] = deque(maxlen=15)
    log = joblog.open_current()
    if log:
        log.write("$ " + shlex.join(argv))
    try:
        buf = b""
        while chunk := await proc.stdout.read(65536):
            *lines, buf = re.split(rb"[\r\n]+", buf + chunk)
            for raw in lines:
                _emit(raw, tail, on_line, log)
        _emit(buf, tail, on_line, log)
        rc = await proc.wait()
    except asyncio.CancelledError:
        _killpg(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            _killpg(proc, signal.SIGKILL)
            await proc.wait()
        raise
    finally:
        if log:
            log.write(f"[code {proc.returncode}]")
            log.close(list(tail))
    if rc:
        raise CmdError(f"{argv[0]} code {rc}: " + " | ".join(list(tail)[-3:]), rc)
    return list(tail)
