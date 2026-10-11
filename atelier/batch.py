import re

from . import translate
from .config import cfg

NUM_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


def numbered(items: list[tuple[int, str]]) -> str:
    return "\n".join(f"[{n}] {t}" for n, t in items)


def parse_numbered(out: str, ids: list[int]) -> dict[int, str] | None:
    res: dict[int, str] = {}
    last = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if m := NUM_RE.match(line):
            last = int(m[1])
            if last in res:
                return None
            res[last] = m[2].strip()
        elif last is not None:
            res[last] = f"{res[last]} {line.strip()}"
    return res if list(res) == ids else None


class Translator:
    def __init__(self, src: str, tgt: str, glossary: list[tuple[str, str]]):
        self.src, self.tgt, self.glossary = src, tgt, glossary
        self.model = cfg["ollama"]["translate_model"]
        self.num_ctx = int(cfg["subtitles"]["num_ctx"])

    async def _ask(self, msgs: list[dict], temp: float) -> str:
        return await translate.complete(self.model, msgs, temperature=temp, num_ctx=self.num_ctx)

    def prompt(self, text: str) -> str:
        return translate.build_prompt(self.src, self.tgt, text, self.glossary)

    async def single(self, text: str) -> str:
        out = await self._ask([{"role": "user", "content": self.prompt(text)}], 0)
        return " ".join(out.split()) or text

    async def batch(self, items: list[tuple[int, str]], prev: list[dict]) -> dict[int, str]:
        if len(items) == 1:
            return {items[0][0]: await self.single(items[0][1])}
        ids = [n for n, _ in items]
        msgs = prev + [{"role": "user", "content": self.prompt(numbered(items))}]
        for attempt in range(2):
            got = parse_numbered(await self._ask(msgs, 0 if attempt == 0 else 0.4), ids)
            if got and all(got.values()):
                return got
        mid = len(items) // 2
        return {**await self.batch(items[:mid], prev), **await self.batch(items[mid:], prev)}
