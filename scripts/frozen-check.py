"""Smoke test of a running Atelier (frozen binary in CI): every GET route, static files, SSE, upload, glossary.
No external tool needed. Usage: python scripts/frozen-check.py [base_url] [log_file]. Exit 1 on any failure."""
import json
import re
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7777").rstrip("/")
LOG = sys.argv[2] if len(sys.argv) > 2 else ""
PARAMS = {"jid": "999999", "name": "absent", "sid": "absent", "target": "absent", "vid": "absent"}
SLOW = {"/api/deps", "/api/profile", "/api/disk", "/api/services", "/api/maint"}
fails = []


def req(method: str, path: str, body: bytes | None = None, ctype: str = "application/json", timeout: float = 60):
    r = urllib.request.Request(BASE + path, data=body, method=method, headers={"Content-Type": ctype} if body is not None else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  {detail[:300]}"))
    if not ok:
        fails.append(label)


st, raw = req("GET", "/openapi.json")
check("/openapi.json", st == 200, str(st))
spec = json.loads(raw) if st == 200 else {"paths": {}}
for path, ops in sorted(spec["paths"].items()):
    if "get" not in ops:
        continue
    url = re.sub(r"\{(\w+)\}", lambda m: PARAMS.get(m.group(1), "x"), path)
    if path == "/api/events":
        continue
    st, raw = req("GET", url, timeout=120 if path in SLOW else 30)
    check(f"GET {url} -> {st}", st < 500, raw.decode("utf-8", "replace"))

st, raw = req("GET", "/")
check("GET / (index.html)", st == 200 and b"<html" in raw.lower(), str(st))
for asset in sorted(set(re.findall(rb'(?:src|href)="([\w./-]+\.(?:js|css|svg))"', raw)) | {b"icons.svg"}):
    st, _ = req("GET", "/" + asset.decode())
    check(f"static {asset.decode()} -> {st}", st == 200)

with urllib.request.urlopen(BASE + "/api/events", timeout=10) as resp:
    first = resp.readline()
    check("SSE /api/events", resp.status == 200 and resp.headers.get_content_type() == "text/event-stream" and first.startswith(b"retry:"),
          f"{resp.status} {resp.headers.get_content_type()} {first!r}")

st, raw = req("POST", "/api/upload?name=frozen-check.txt", b"bonjour\n", "application/octet-stream")
check(f"POST /api/upload -> {st}", st == 200 and b"path" in raw, raw.decode("utf-8", "replace"))
st, raw = req("PUT", "/api/glossaries/frozen-check", json.dumps({"text": "a=b"}).encode())
check(f"PUT /api/glossaries -> {st}", st == 200, raw.decode("utf-8", "replace"))
st, raw = req("DELETE", "/api/glossaries/frozen-check")
check(f"DELETE /api/glossaries -> {st}", st == 200, raw.decode("utf-8", "replace"))
st, raw = req("POST", "/api/jobs", json.dumps({"kind": "nope", "params": {}}).encode())
check(f"POST /api/jobs (kind inconnu) -> {st}", 400 <= st < 500, raw.decode("utf-8", "replace"))

if LOG:
    try:
        text = open(LOG, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    bad = re.findall(r"^.*(?:Traceback|ImportError|ModuleNotFoundError|FileNotFoundError).*$", text, re.M)
    check("log sans Traceback/ImportError", not bad, "\n".join(bad[:5]))

print(f"{len(fails)} échec(s)" if fails else "tout ok")
sys.exit(1 if fails else 0)
