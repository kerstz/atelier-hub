"""Profile -> tier -> recommended models per role. Pure functions over data: easy to test.
Sizes are 4-bit quantised downloads (~ VRAM before context). Tags marked nv are not verified."""
GIB = 1 << 30

# role models (Ollama tags) + preferred translation engine + context window
TIERS: dict[str, dict] = {
    "gpu-24": {"label": "GPU ≥ 24 Go", "engine": "ollama", "num_ctx": 8192,
               "models": {"translate": "translategemma:27b", "second": "gemma3:27b", "vision": "gemma3:27b"}},
    "gpu-16": {"label": "GPU 14-24 Go", "engine": "ollama", "num_ctx": 8192,
               "models": {"translate": "translategemma:12b", "second": "gemma3:12b", "vision": "gemma3:12b"}},
    "gpu-8": {"label": "GPU 7-14 Go", "engine": "ollama", "num_ctx": 4096,
              "models": {"translate": "translategemma:4b", "second": "gemma3:4b", "vision": "gemma3:4b"}},
    "gpu-4": {"label": "GPU 3,5-7 Go", "engine": "ollama", "num_ctx": 4096,
              "models": {"translate": "translategemma:4b", "second": "gemma3:4b", "vision": "gemma3:4b"}},
    "cpu-16": {"label": "CPU seul, ≥ 15 Go de RAM", "engine": "ctranslate2", "num_ctx": 4096, "ct2": "nllb-200-distilled-1.3B",
               "models": {"translate": "translategemma:4b", "second": "gemma3:4b", "vision": "gemma3:4b"}},
    "cpu-small": {"label": "CPU seul, petite machine", "engine": "ctranslate2", "num_ctx": 2048, "ct2": "nllb-200-distilled-600M",
                  "models": {"translate": "gemma3:1b", "second": "gemma3:1b", "vision": ""}},
}
APPROX_GB = {"translategemma:27b": 17, "gemma3:27b": 17, "translategemma:12b": 8.1, "gemma3:12b": 8.1,
             "translategemma:4b": 3.3, "gemma3:4b": 3.3, "gemma3:1b": 0.8}


def tier_of(p: dict) -> str:
    v = p.get("vram_total", 0)
    if v >= 23 * GIB:
        return "gpu-24"
    if v >= 14 * GIB:
        return "gpu-16"
    if v >= 7 * GIB:
        return "gpu-8"
    if v >= 3.5 * GIB:
        return "gpu-4"
    # CPU only: Ollama on CPU needs AVX2 and room; below that, NLLB int8 is the only sane choice
    if p.get("ram_total", 0) >= 15 * GIB and p.get("avx2", True):
        return "cpu-16"
    return "cpu-small"


def recommend(p: dict) -> dict:
    t = tier_of(p)
    spec = TIERS[t]
    notes = []
    if t.startswith("cpu"):
        notes.append("Pas de GPU exploitable: traduction par NLLB (CTranslate2) conseillée, LLM seulement pour le texte libre.")
    if p.get("ram_avail") and t == "cpu-16" and p["ram_avail"] < 6 * GIB:
        notes.append("Peu de RAM disponible en ce moment: fermer des applications avant un gros document.")
    if t == "cpu-small":
        notes.append("Petite machine: PDF (pdf2zh) et vision indisponibles, résumé limité.")
    if p.get("vram_free", 0) and p.get("vram_total", 0) and p["vram_free"] < 0.5 * p["vram_total"]:
        notes.append("Le bureau occupe déjà une bonne part de la VRAM.")
    return {"tier": t, "label": spec["label"], "engine": spec["engine"], "num_ctx": spec["num_ctx"],
            "models": dict(spec["models"]), "ct2_model": spec.get("ct2", ""), "notes": notes,
            "download_gb": {m: APPROX_GB.get(m) for m in set(spec["models"].values()) if m}}
