import re
import textwrap
from dataclasses import dataclass

TIME_RE = re.compile(r"(\d+:\d\d:\d\d[,.]\d{1,3})\s*-->\s*(\d+:\d\d:\d\d[,.]\d{1,3})")
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


@dataclass
class Cue:
    start: str
    end: str
    text: str


def parse(raw: str) -> list[Cue]:
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines[:2]):
            if m := TIME_RE.search(line):
                cues.append(Cue(m[1].replace(".", ","), m[2].replace(".", ","), "\n".join(lines[i + 1 :]).strip()))
                break
    return cues


def flat(text: str) -> str:
    return " ".join(TAG_RE.sub("", text).split())


def wrap(text: str, width: int = 42) -> str:
    if len(text) <= width:
        return text
    if len(text) <= 2 * width + 8:
        spaces = [i for i, c in enumerate(text) if c == " "]
        if spaces:
            i = min(spaces, key=lambda i: abs(i - len(text) // 2))
            return text[:i] + "\n" + text[i + 1 :]
    return "\n".join(textwrap.wrap(text, width))


def build(cues: list[Cue], texts: list[str]) -> str:
    out = []
    for n, (c, t) in enumerate(zip(cues, texts), 1):
        out.append(f"{n}\n{c.start} --> {c.end}\n{wrap(t)}\n")
    return "\n".join(out)
