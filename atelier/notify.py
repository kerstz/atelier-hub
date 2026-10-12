import asyncio
import shutil

from .config import ROOT, cfg

SILENT = {"demo", "dictate"}


def finished(job: dict | None, params: dict, secs: float) -> None:
    """Desktop notification at job end. Never raises: a missing notify-send must not fail a job."""
    d = cfg["desktop"]
    if not job or not d["notify"] or job["kind"] in SILENT or (job["kind"] == "tts" and params.get("mode") != "mp3"):
        return
    failed = job["status"] == "failed"
    if not failed and secs < float(d["notify_min_seconds"]):
        return
    bin_ = shutil.which("notify-send")
    if not bin_:
        return
    title = ("Échec : " if failed else "Terminé : ") + (job["title"] or job["kind"])
    body = (job.get("error") or job.get("message") or "")[:200]
    icon = ROOT / "static" / "icon.svg"
    argv = [bin_, "-a", "Atelier", "-i", str(icon), "-u", "critical" if failed else "normal", "--", title[:100]]
    if body:
        argv.append(body)

    async def fire() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.wait(), 5)
        except Exception:
            pass

    asyncio.get_running_loop().create_task(fire())
