import json
import re
import time
import urllib.request

from .config import VERSION, cfg

URL = "https://api.github.com/repos/kerstz/atelier-hub/releases/latest"
TTL_OK, TTL_FAIL = 6 * 3600, 1800
_cache: dict = {"at": 0.0, "ttl": 0.0, "data": None}


def _nums(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def _fetch() -> dict:
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json", "User-Agent": f"atelier/{VERSION}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.load(r)
    tag, url = str(data.get("tag_name") or ""), str(data.get("html_url") or "")
    if not tag or not url.startswith("https://github.com/"):
        raise ValueError("réponse inattendue")
    return {"latest": tag.lstrip("v"), "url": url}


def check() -> dict:
    if not cfg["update"]["check"]:
        return {"latest": None, "enabled": False}
    if time.time() - _cache["at"] < _cache["ttl"]:
        return _cache["data"]
    try:
        info, ttl = _fetch(), TTL_OK
    except Exception:
        info, ttl = {"latest": None}, TTL_FAIL
    newer = bool(info["latest"]) and _nums(info["latest"]) > _nums(VERSION) and bool(_nums(VERSION))
    data = {**info, "enabled": True, "current": VERSION, "newer": newer}
    _cache.update(at=time.time(), ttl=ttl, data=data)
    return data
