import asyncio
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from . import db


@dataclass
class Kind:
    handler: Callable[["Ctx", dict], Awaitable[str | None]]
    gpu: bool | Callable[[dict], bool] = False


KINDS: dict[str, Kind] = {}


def register(name: str, handler, gpu=False) -> None:
    KINDS[name] = Kind(handler, gpu)


class Ctx:
    def __init__(self, mgr: "Manager", jid: int):
        self.mgr, self.id = mgr, jid

    def set(self, progress: float | None = None, message: str | None = None) -> None:
        f = {}
        if progress is not None:
            f["progress"] = max(0.0, min(1.0, progress))
        if message is not None:
            f["message"] = message
        if f:
            self.mgr.update(self.id, **f)

    def delta(self, text: str) -> None:
        self.mgr.emit("delta", {"id": self.id, "text": text})


class Manager:
    def __init__(self):
        self.gpu_lock = asyncio.Lock()
        self.tasks: dict[int, asyncio.Task] = {}
        self.subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subs.discard(q)

    def emit(self, event: str, payload: dict) -> None:
        item = (event, json.dumps(payload))
        for q in list(self.subs):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                self.subs.discard(q)

    def update(self, jid: int, **f) -> None:
        db.update(jid, **f)
        self.emit("job", db.get(jid))

    def submit(self, kind: str, title: str, params: dict) -> dict:
        k = KINDS[kind]
        gpu = k.gpu(params) if callable(k.gpu) else k.gpu
        jid = db.insert(kind, title, params, gpu)
        self.tasks[jid] = asyncio.create_task(self._run(jid, k, params, gpu))
        self.update(jid)
        return db.get(jid)

    async def _run(self, jid: int, k: Kind, params: dict, gpu: bool) -> None:
        held = False
        try:
            if gpu:
                await self.gpu_lock.acquire()
                held = True
            self.update(jid, status="running", started=time.time())
            out = await k.handler(Ctx(self, jid), params)
            self.update(jid, status="done", progress=1.0, output=out, finished=time.time())
        except asyncio.CancelledError:
            self.update(jid, status="cancelled", finished=time.time())
        except Exception as e:
            self.update(jid, status="failed", error=str(e), finished=time.time())
        finally:
            if held:
                self.gpu_lock.release()
            self.tasks.pop(jid, None)

    def cancel(self, jid: int) -> bool:
        t = self.tasks.get(jid)
        if t:
            t.cancel()
        return t is not None


manager = Manager()


async def _demo(ctx: Ctx, p: dict) -> None:
    steps = int(p.get("seconds", 5))
    for i in range(steps):
        await asyncio.sleep(1)
        ctx.set((i + 1) / steps, f"étape {i + 1}/{steps}")


register("demo", _demo, gpu=lambda p: bool(p.get("gpu")))
