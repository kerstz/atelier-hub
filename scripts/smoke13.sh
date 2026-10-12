#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
base="http://127.0.0.1:${ATELIER_PORT:-7777}"
fail=0
t() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# --- hors-ligne: vrai FastAPI (TestClient) + vrais jobs, ollama simulé
py - "$tmp" <<'PY'
import sys, time, asyncio, pathlib
from atelier.config import cfg

d = pathlib.Path(sys.argv[1])
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(); (d / "out").mkdir()
cfg["desktop"]["notify"] = False

from atelier import jobs, joblog, ollama, proc
from atelier.jobs import register
from fastapi.testclient import TestClient
from atelier.main import app

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

async def h_ok(ctx, p):
    await proc.run_cmd(["sh", "-c", "echo hello-log; printf '\\033[31mred\\033[0m\\n'"])
async def h_fail(ctx, p):
    await proc.run_cmd(["sh", "-c", "echo before-fail; exit 3"])
async def h_slow(ctx, p):
    await asyncio.sleep(60)
async def h_flood(ctx, p):
    await proc.run_cmd(["sh", "-c", "i=0; while [ $i -lt 3000 ]; do printf 'x%.0s' $(seq 800); echo; i=$((i+1)); done; echo LAST-LINE"])
async def h_noop(ctx, p):
    return None
register("t_ok", h_ok); register("t_fail", h_fail); register("t_slow", h_slow); register("t_flood", h_flood)
register("t_gpu", h_noop, gpu=True, frees_vram=True)
register("t_gpu_ollama", h_noop, gpu=True)

unloaded = []
async def fake_loaded():
    return {"up": True, "models": [{"name": "gemma3:12b"}]}
async def fake_unload(m):
    unloaded.append(m)
ollama.loaded, ollama.unload = fake_loaded, fake_unload

with TestClient(app, base_url="http://127.0.0.1") as c:
    def upload(name="a.txt"):
        return c.post(f"/api/upload?name={name}", content=b"data").json()["path"]
    def submit(kind, **params):
        return c.post("/api/jobs", json={"kind": kind, "title": f"t {kind}", "params": params}).json()["id"]
    def wait(jid, want=("done", "failed", "cancelled"), secs=20):
        for _ in range(secs * 20):
            j = next(x for x in c.get("/api/jobs").json() if x["id"] == jid)
            if j["status"] in want:
                return j
            time.sleep(0.05)
        raise SystemExit(f"timeout job {jid}")

    up = upload()
    j = wait(submit("t_ok", path=up))
    log = c.get(f"/api/jobs/{j['id']}/log").text
    check("succès: upload consommé", j["status"] == "done" and not pathlib.Path(up).exists())
    check("journal: commande, sortie, code", "$ sh -c" in log and "hello-log" in log and "[code 0]" in log)
    check("journal: ANSI retiré", "\x1b" not in log and "red" in log)

    up = upload()
    j = wait(submit("t_fail", path=up))
    log = c.get(f"/api/jobs/{j['id']}/log").text
    check("échec: upload conservé", j["status"] == "failed" and pathlib.Path(up).exists())
    check("échec: journal avec sortie + traceback", "before-fail" in log and "== échec ==" in log and "CmdError" in log)
    r = c.post(f"/api/jobs/{j['id']}/retry")
    check("relancer: nouvelle tâche même type/params", r.status_code == 200 and r.json()["id"] != j["id"] and r.json()["kind"] == "t_fail")
    wait(r.json()["id"])
    check("relancer: tâche réussie refusée (400)", c.post(f"/api/jobs/{wait(submit('t_ok'))['id']}/retry").status_code == 400)
    pathlib.Path(up).unlink()
    check("relancer: source supprimée -> 410", c.post(f"/api/jobs/{j['id']}/retry").status_code == 410)
    r = c.post("/api/jobs/999999/retry")
    check("relancer: inconnu -> 404", r.status_code == 404 and "inconnue" in r.text)

    up = upload("b.txt")
    jid = submit("t_slow", path=up)
    wait(jid, want=("running",))
    c.post(f"/api/jobs/{jid}/cancel")
    j = wait(jid)
    check("annulé: upload conservé + relançable", j["status"] == "cancelled" and pathlib.Path(up).exists()
          and c.post(f"/api/jobs/{jid}/retry").status_code == 200)
    c.post(f"/api/jobs/{c.get('/api/jobs').json()[0]['id']}/cancel")

    wait(submit("t_gpu"))
    check("job GPU hors Ollama: modèles déchargés", unloaded == ["gemma3:12b"])
    wait(submit("t_gpu_ollama"))
    check("job GPU Ollama: pas de déchargement", unloaded == ["gemma3:12b"])
    cfg["gpu"]["free_vram"] = False
    wait(submit("t_gpu"))
    check("free_vram=false respecté", unloaded == ["gemma3:12b"])
    cfg["gpu"]["free_vram"] = True

    j = wait(submit("t_flood"), secs=60)
    p = joblog.path(j["id"])
    txt = p.read_text()
    check("journal plafonné (cap + 16 Ko)", p.stat().st_size < joblog.CAP + 16384)
    check("journal tronqué: marqueur + dernière ligne conservée", "journal tronqué" in txt and "LAST-LINE" in txt)

    before = joblog.path(j["id"]).exists()
    c.post("/api/jobs/clear")
    check("vider l'historique supprime les journaux", before and not joblog.path(j["id"]).exists())
    check("journal d'une tâche inconnue -> 404", c.get("/api/jobs/999999/log").status_code == 404)

import os, time as _t
old = joblog.path(424242); old.parent.mkdir(exist_ok=True); old.write_text("x")
os.utime(old, (_t.time() - 20 * 86400,) * 2)
joblog.purge(14)
check("purge des journaux > 14 j", not old.exists())
raise SystemExit(0 if ok else 1)
PY
t "jobs: journal, relance, uploads, VRAM" "[ $? = 0 ]"

# --- live
curl -fsS "$base/" >/dev/null 2>&1 || { echo "service down: live ignoré"; exit $fail; }
t "service: relance (nouveau code)" "curl -s -X POST $base/api/jobs/999999/retry | grep -q 'inconnue'"
t "service: journal (nouveau code)" "[ \$(curl -s -o /dev/null -w '%{http_code}' $base/api/jobs/999999/log) = 404 ]"
exit $fail
