import httpx

from .config import cfg


def _url(path: str) -> str:
    return cfg["ollama"]["url"].rstrip("/") + path


async def loaded() -> dict:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(_url("/api/ps"))
            r.raise_for_status()
    except httpx.HTTPError:
        return {"up": False, "models": []}
    models = []
    for m in r.json().get("models", []):
        size, vram = m.get("size") or 0, m.get("size_vram") or 0
        models.append(
            {
                "name": m["name"],
                "size": size,
                "gpu_pct": round(100 * vram / size) if size else 0,
                "expires_at": m.get("expires_at"),
            }
        )
    return {"up": True, "models": models}


async def unload(model: str) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(_url("/api/generate"), json={"model": model, "keep_alive": 0})
        r.raise_for_status()


async def unload_all() -> list[str]:
    """Best-effort: free VRAM before a non-Ollama GPU job. Never raises (Ollama may be down)."""
    gone = []
    for m in (await loaded())["models"]:
        try:
            await unload(m["name"])
            gone.append(m["name"])
        except httpx.HTTPError:
            pass
    return gone


async def exclusive(model: str) -> None:
    """Free VRAM: unload every loaded model except `model`."""
    want = model if ":" in model else f"{model}:latest"
    for m in (await loaded())["models"]:
        if m["name"] != want:
            try:
                await unload(m["name"])
            except httpx.HTTPError:
                pass
