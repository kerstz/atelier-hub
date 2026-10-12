"""Translation engines behind one small interface. `ollama` = LLM through Ollama (prompted, numbered
batches); `ctranslate2` = NLLB-200 on CPU (no prompt: every segment translated on its own).
`pick()` honours [translate] engine and, in "auto", only ever chooses among what is already installed."""
import asyncio
import re
import time
from pathlib import Path

import httpx

from . import hw, tiers
from .config import cfg

MARK_RE = re.compile(r"⟦\d+⟧")
TAG_RE = re.compile(r"</?(?:b|i|a\d+)>")
MAX_CHARS = 800  # NLLB handles ~512 tokens per segment

NLLB = {
    "en": "eng_Latn", "fr": "fra_Latn", "es": "spa_Latn", "de": "deu_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "pt-BR": "por_Latn", "nl": "nld_Latn", "pl": "pol_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "cs": "ces_Latn",
    "sv": "swe_Latn", "tr": "tur_Latn", "ar": "arb_Arab", "hi": "hin_Deva", "vi": "vie_Latn", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "zh": "zho_Hans", "zh-TW": "zho_Hant", "fil": "tgl_Latn", "ceb": "ceb_Latn", "id": "ind_Latn",
    "ms": "zsm_Latn", "th": "tha_Thai", "he": "heb_Hebr", "fa": "pes_Arab", "bn": "ben_Beng", "el": "ell_Grek",
    "ro": "ron_Latn", "hu": "hun_Latn", "bg": "bul_Cyrl", "da": "dan_Latn", "fi": "fin_Latn",
}


# ---- models per role ("auto" -> recommendation for this machine)

def model(role: str) -> str:
    """role: translate | second | vision. An explicit value in config.toml always wins."""
    v = cfg["ollama"][f"{role}_model"]
    if v and v != "auto":
        return v
    return tiers.recommend(hw.profile())["models"].get(role, "")


# ---- Ollama availability (cached 20 s)
_tags: tuple[float, set[str] | None] = (0.0, None)


async def ollama_models() -> set[str] | None:
    """Installed model names, or None when Ollama is unreachable."""
    global _tags
    if time.monotonic() - _tags[0] < 20:
        return _tags[1]
    names: set[str] | None = None
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(cfg["ollama"]["url"].rstrip("/") + "/api/tags")
            names = {m["name"] for m in r.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        pass
    _tags = (time.monotonic(), names)
    return names


def has_model(names: set[str], m: str) -> bool:
    return m in names or (":" not in m and f"{m}:latest" in names)


# ---- CTranslate2 / NLLB
def ct2_dir() -> Path:
    return Path(cfg["ctranslate2"]["model_dir"]).expanduser()


def ct2_ready() -> bool:
    d = ct2_dir()
    return d.is_dir() and (d / "model.bin").is_file() and any(d.glob("*.model"))


class CT2Engine:
    name = "ctranslate2"
    gpu = False  # CPU: takes the CPU slot, not the GPU lock

    def __init__(self):
        self._tr = self._sp = None

    def _load(self):
        if self._tr is None:
            try:
                import ctranslate2
                import sentencepiece
            except ImportError:
                raise RuntimeError("moteur ctranslate2 absent: uv pip install ctranslate2 sentencepiece") from None
            d = ct2_dir()
            if not ct2_ready():
                raise RuntimeError(f"modèle NLLB absent dans {d} (voir install.sh --engine=ct2)")
            threads = int(cfg["ctranslate2"]["threads"]) or hw.profile()["cores"]
            self._tr = ctranslate2.Translator(str(d), device="cpu", compute_type="int8", inter_threads=1, intra_threads=threads)
            self._sp = sentencepiece.SentencePieceProcessor()
            self._sp.load(str(next(d.glob("*.model"))))
        return self._tr, self._sp

    def _one(self, text: str, src: str, tgt: str) -> str:
        tr, sp = self._load()
        if tgt not in NLLB or (src != "auto" and src not in NLLB):
            raise RuntimeError("langue non couverte par NLLB")
        s_code = NLLB.get(src, NLLB["en"])  # "auto": NLLB needs a source tag; English is the least-bad guess
        markers = MARK_RE.findall(text)
        clean = " ".join(TAG_RE.sub("", MARK_RE.sub(" ", text)).split())
        if not clean:
            return text
        pieces = [clean[i:i + MAX_CHARS] for i in range(0, len(clean), MAX_CHARS)] if len(clean) > MAX_CHARS else [clean]
        out = []
        for p in pieces:
            tokens = [s_code] + sp.encode(p, out_type=str) + ["</s>"]
            res = tr.translate_batch([tokens], target_prefix=[[NLLB[tgt]]], beam_size=4,
                                     max_decoding_length=max(64, int(len(tokens) * 2.2)), repetition_penalty=1.1)
            out.append(sp.decode(res[0].hypotheses[0][1:]))
        return " ".join(out) + ("".join(markers) and " " + "".join(markers))

    async def translate_items(self, items: list[tuple[int, str]], src: str, tgt: str) -> dict[int, str]:
        def work() -> dict[int, str]:
            return {n: self._one(t, src, tgt) for n, t in items}
        return await asyncio.to_thread(work)


class OllamaEngine:
    name = "ollama"
    gpu = True


_ct2 = CT2Engine()
_ollama = OllamaEngine()


async def pick():
    """Engine for translation work. Never downloads or installs anything."""
    want = cfg["translate"].get("engine", "auto")
    if want == "ctranslate2":
        return _ct2
    if want == "ollama":
        return _ollama
    names = await ollama_models()
    rec = tiers.recommend(hw.profile())
    if names is not None and has_model(names, model("translate")) and rec["engine"] == "ollama":
        return _ollama
    if ct2_ready():
        return _ct2
    return _ollama  # let the usual "Ollama injoignable" / "modèle introuvable" error explain what is missing


async def describe() -> dict:
    """What the System panel shows: profile, recommendation, engine actually used and why."""
    p = hw.profile()
    rec = tiers.recommend(p)
    eng = await pick()
    names = await ollama_models()
    missing = [m for m in {rec["models"].get(r) for r in ("translate", "second", "vision")} if m and names is not None and not has_model(names, m)]
    return {"profile": p, "recommendation": rec, "engine": eng.name, "ollama_up": names is not None,
            "ct2_ready": ct2_ready(), "missing_models": sorted(missing), "configured": cfg["translate"].get("engine", "auto")}
