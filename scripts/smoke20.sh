#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
fail=0
t() { if ( eval "$2" ); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
py() { PYTHONPATH=. uv run --frozen --offline python "$@"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

t "install.sh --models --engine=ct2 (dry-run)" "./install.sh --dry-run --yes --models --engine=ct2 | grep -q 'recommended for this machine' && ./install.sh --dry-run --yes --engine=ct2 | grep -q 'ctranslate2 sentencepiece'"
t "python -m atelier.hw: palier + modèles" "uv run --frozen --offline python -m atelier.hw | grep -q '^tier'"
t "python -m atelier.hw --models: liste de tags" "[ \$(uv run --frozen --offline python -m atelier.hw --models | wc -l) -ge 1 ]"

py - "$tmp" <<'PY'
import sys, os, asyncio, json, types, pathlib, time
d = pathlib.Path(sys.argv[1])
from atelier.config import cfg
cfg["paths"]["output"] = str(d / "out"); cfg["paths"]["data"] = str(d / "data")
(d / "data").mkdir(); (d / "out").mkdir()
cfg["desktop"]["notify"] = False

ok = True
def check(name, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + name); ok &= bool(cond)

from atelier import hw, tiers, engines, translate
GIB = 1 << 30

# ---- paliers (fonction pure)
P = lambda vram=0, ram=32, avx2=True: {"vram_total": vram * GIB, "vram_free": vram * GIB, "ram_total": ram * GIB, "ram_avail": ram * GIB // 2, "avx2": avx2}
for name, p, tier, tr in [
    ("GPU 24 Go", P(24), "gpu-24", "translategemma:27b"), ("GPU 16 Go", P(16), "gpu-16", "translategemma:12b"),
    ("GPU 12 Go", P(12), "gpu-8", "translategemma:4b"), ("GPU 8 Go", P(8), "gpu-8", "translategemma:4b"),
    ("GPU 6 Go", P(6), "gpu-4", "translategemma:4b"), ("GPU 4 Go", P(4), "gpu-4", "translategemma:4b"),
    ("CPU 32 Go AVX2", P(0, 32), "cpu-16", "translategemma:4b"), ("CPU 8 Go", P(0, 8), "cpu-small", "gemma3:1b"),
    ("CPU 32 Go sans AVX2", P(0, 32, False), "cpu-small", "gemma3:1b"), ("GPU 2 Go (iGPU) + 4 Go RAM", P(2, 4), "cpu-small", "gemma3:1b"),
]:
    r = tiers.recommend(p)
    check(f"palier: {name} -> {tier}", r["tier"] == tier and r["models"]["translate"] == tr)
check("palier CPU: moteur ctranslate2 + modèle NLLB", tiers.recommend(P(0, 8))["engine"] == "ctranslate2" and tiers.recommend(P(0, 8))["ct2_model"].endswith("600M"))
check("palier CPU 16: NLLB 1.3B", tiers.recommend(P(0, 32))["ct2_model"].endswith("1.3B"))
check("petite machine: vision désactivée", tiers.recommend(P(0, 8))["models"]["vision"] == "")
check("GPU: moteur ollama", tiers.recommend(P(16))["engine"] == "ollama")

# ---- détection (faux sysfs/proc/nvidia-smi)
sysfs, proc = d / "sys", d / "proc"
def card(n, vendor, total, used):
    dev = sysfs / "class/drm" / f"card{n}" / "device"; dev.mkdir(parents=True)
    (dev / "vendor").write_text(vendor); (dev / "mem_info_vram_total").write_text(str(total)); (dev / "mem_info_vram_used").write_text(str(used))
card(0, "0x1002", 8 * GIB, 2 * GIB)                  # AMD 8 Go
card(1, "0x8086", 512 << 20, 100 << 20)               # iGPU Intel
proc.mkdir()
(proc / "meminfo").write_text("MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\n")
(proc / "cpuinfo").write_text("processor : 0\nflags : fpu sse4_2 avx avx2 fma\n")
os.environ.update(ATELIER_SYSFS_ROOT=str(sysfs), ATELIER_PROC_ROOT=str(proc), ATELIER_NVSMI="")
hw._cached.cache_clear()
p = hw.profile(refresh=True)
check("détection: meilleur GPU = AMD 8 Go (iGPU ignoré)", p["gpu"]["vendor"] == "amd" and p["vram_total"] == 8 * GIB and p["vram_free"] == 6 * GIB)
check("détection: iGPU marqué igpu", any(g["igpu"] and g["vendor"] == "intel" for g in p["gpus"]))
check("détection: RAM 16 Go, avx2", p["ram_total"] == 16384000 * 1024 and p["avx2"] and not p["avx512"])
nv = d / "nvsmi"; nv.write_text("#!/bin/sh\necho 'NVIDIA GeForce RTX 3060, 12288, 1024'\n"); nv.chmod(0o755)
os.environ["ATELIER_NVSMI"] = str(nv)
p = hw.profile(refresh=True)
check("détection: NVIDIA via nvidia-smi (12 Go gagne)", p["gpu"]["vendor"] == "nvidia" and p["vram_total"] == 12 << 30 and tiers.tier_of(p) == "gpu-8")
os.environ["ATELIER_NVSMI"] = ""
shutil_which = __import__("shutil").which
(proc / "meminfo").write_text("MemTotal: 4000000 kB\nMemAvailable: 1000000 kB\n")
for c in (sysfs / "class/drm").iterdir():
    __import__("shutil").rmtree(c)
p = hw.profile(refresh=True)
check("détection: sans GPU, 4 Go de RAM -> cpu-small", p["vram_total"] == 0 and tiers.tier_of(p) == "cpu-small")

# ---- modèles "auto" vs explicites
cfg["ollama"]["translate_model"] = "auto"
check("model(): auto -> recommandation du matériel", engines.model("translate") == "gemma3:1b")
cfg["ollama"]["translate_model"] = "mon-modele:7b"
check("model(): valeur explicite prioritaire", engines.model("translate") == "mon-modele:7b")

# ---- choix du moteur
async def tags_server(names):
    async def handle(r, w):
        await r.read(4096)
        body = json.dumps({"models": [{"name": n} for n in names]}).encode()
        w.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        await w.drain(); w.close()
    return await asyncio.start_server(handle, "127.0.0.1", 0)
def reset_cache():
    engines._tags = (0.0, None)
async def pick_case():
    out = {}
    cfg["ollama"]["translate_model"] = "translategemma:4b"
    cfg["translate"]["engine"] = "auto"
    # GPU 8 Go + Ollama up with the model -> ollama
    (proc / "meminfo").write_text("MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n")
    card(0, "0x1002", 8 * GIB, 0); hw.profile(refresh=True)
    srv = await tags_server(["translategemma:4b"]); cfg["ollama"]["url"] = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    reset_cache(); out["gpu_up"] = (await engines.pick()).name
    srv.close()
    # Ollama unreachable, no CT2 model -> ollama (explains what is missing)
    cfg["ollama"]["url"] = "http://127.0.0.1:9"; reset_cache(); out["down_no_ct2"] = (await engines.pick()).name
    # Ollama unreachable + CT2 model installed -> ctranslate2
    m = d / "nllb"; m.mkdir(); (m / "model.bin").write_bytes(b"x"); (m / "sentencepiece.bpe.model").write_bytes(b"x")
    cfg["ctranslate2"]["model_dir"] = str(m); reset_cache(); out["down_ct2"] = (await engines.pick()).name
    # explicit choices win
    cfg["translate"]["engine"] = "ollama"; out["forced_ollama"] = (await engines.pick()).name
    cfg["translate"]["engine"] = "ctranslate2"; out["forced_ct2"] = (await engines.pick()).name
    cfg["translate"]["engine"] = "auto"
    # CPU-only machine with the model installed: ctranslate2 even though Ollama answers
    import shutil
    shutil.rmtree(sysfs / "class/drm/card0"); hw.profile(refresh=True)
    srv = await tags_server(["translategemma:4b", "gemma3:1b"]); cfg["ollama"]["url"] = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    reset_cache(); out["cpu_up"] = (await engines.pick()).name
    srv.close()
    return out
o = asyncio.run(pick_case())
check("pick: GPU + Ollama + modèle présent -> ollama", o["gpu_up"] == "ollama")
check("pick: Ollama muet, pas de NLLB -> ollama (erreur explicite ensuite)", o["down_no_ct2"] == "ollama")
check("pick: Ollama muet + NLLB installé -> ctranslate2", o["down_ct2"] == "ctranslate2")
check("pick: réglages explicites respectés", o["forced_ollama"] == "ollama" and o["forced_ct2"] == "ctranslate2")
check("pick: machine CPU + NLLB installé -> ctranslate2", o["cpu_up"] == "ctranslate2")

# ---- moteur CT2 avec faux ctranslate2 / sentencepiece
calls = []
class FakeResult:
    def __init__(self, toks): self.hypotheses = [toks]
class FakeTranslator:
    def __init__(self, path, device, compute_type, inter_threads, intra_threads):
        calls.append(("init", device, compute_type, intra_threads))
    def translate_batch(self, batch, target_prefix, **kw):
        calls.append(("batch", batch[0], target_prefix[0], kw.get("beam_size")))
        words = [t for t in batch[0][1:-1]]
        return [FakeResult([target_prefix[0][0]] + ["FR_" + w for w in words])]
class FakeSP:
    def load(self, p): pass
    def encode(self, text, out_type=str): return text.split()
    def decode(self, toks): return " ".join(toks)
sys.modules["ctranslate2"] = types.SimpleNamespace(Translator=FakeTranslator)
sys.modules["sentencepiece"] = types.SimpleNamespace(SentencePieceProcessor=FakeSP)
cfg["ctranslate2"]["threads"] = 3
eng = engines.CT2Engine()
res = asyncio.run(eng.translate_items([(1, "Hello <b>big</b> world ⟦1⟧ and ⟦2⟧"), (2, "   ")], "en", "fr"))
init = next(c for c in calls if c[0] == "init"); batch = next(c for c in calls if c[0] == "batch")
check("CT2: CPU int8, 3 threads", init[1:] == ("cpu", "int8", 3))
check("CT2: jeton source = eng_Latn, </s> final", batch[1][0] == "eng_Latn" and batch[1][-1] == "</s>")
check("CT2: préfixe cible = fra_Latn", batch[2] == ["fra_Latn"])
check("CT2: balises retirées avant traduction", not any(("<" in t and t != "</s>") or "⟦" in t for t in batch[1]))
check("CT2: marqueurs ⟦n⟧ rendus en fin de segment", res[1].endswith("⟦1⟧⟦2⟧") and "FR_Hello" in res[1])
check("CT2: segment vide inchangé", res[2] == "   ")
long = " ".join(["word"] * 600)                    # 3000 car. > MAX_CHARS
calls.clear(); asyncio.run(eng.translate_items([(1, long)], "en", "fr"))
check("CT2: long segment découpé (≥ 4 appels)", sum(1 for c in calls if c[0] == "batch") >= 4)
try:
    asyncio.run(eng.translate_items([(1, "x")], "en", "xx")); err = ""
except RuntimeError as e:
    err = str(e)
check("CT2: langue hors NLLB refusée", "NLLB" in err)
check("NLLB: les 35 langues d'Atelier ont un code", set(translate.LANGS) <= set(engines.NLLB))

# ---- intégration: Translator / translate.run / verrous / PDF
from atelier import batch, db, docs
from atelier.jobs import manager
from atelier.util import HEAVY
cfg["translate"]["engine"] = "ctranslate2"
engines._ct2 = engines.CT2Engine()
tr = batch.Translator("en", "fr", [])
out = asyncio.run(tr.batch([(1, "Hello world"), (2, "Good <i>night</i> ⟦3⟧")], []))
check("Translator.batch via CT2: pas de prompt numéroté, marqueur gardé", out[1] == "FR_Hello FR_world" and out[2].endswith("⟦3⟧"))
class Ctx:
    id = 1; deltas = []
    def set(self, *a, **k): pass
    def delta(self, t): self.deltas.append(t)
db.init(); c = Ctx(); c.deltas = []
asyncio.run(translate.run(c, {"text": "Hello world", "src": "en", "tgt": "fr"}))
check("translate.run via CT2: sortie + historique", c.deltas == ["FR_Hello FR_world"] and db.recent_translations()[0]["result"] == "FR_Hello FR_world")
held = {}
orig = engines.CT2Engine._one
def spy(self, text, src, tgt):
    held["gpu"], held["heavy"] = manager.gpu_lock.locked(), HEAVY.locked()
    return orig(self, text, src, tgt)
engines.CT2Engine._one = spy
asyncio.run(docs.translate_texts(Ctx(), ["One sentence."], "en", "fr", [], 0, 1))
engines.CT2Engine._one = orig
check("verrous: moteur CPU prend le créneau CPU, pas le verrou GPU", held == {"gpu": False, "heavy": True})
try:
    asyncio.run(docs.do_pdf(Ctx(), pathlib.Path("/x.pdf"), "x", "en", "fr", [], "", d, d)); err = ""
except RuntimeError as e:
    err = str(e)
check("PDF: moteur CPU -> message clair (convertir en DOCX)", "DOCX" in err)

# ---- API
from fastapi.testclient import TestClient
from atelier.main import app
cfg["translate"]["engine"] = "auto"
with TestClient(app, base_url="http://127.0.0.1:7777") as cl:
    j = cl.get("/api/profile").json()
    check("API /api/profile", {"profile", "recommendation", "engine", "ct2_ready", "missing_models", "configured"} <= set(j) and j["recommendation"]["tier"] == "cpu-16")
raise SystemExit(0 if ok else 1)
PY
t "phase 20 hors-ligne" "[ $? = 0 ]"
exit $fail
