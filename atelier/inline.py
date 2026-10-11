import re
from typing import NamedTuple


class Fmt(NamedTuple):
    b: bool = False
    i: bool = False
    link: int = 0


Seg = tuple[str, Fmt]
TOKEN_RE = re.compile(r"<(/?)(b|i|a(\d+))>")
HTML_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\s*/?>")


def encode(segs: list[Seg]) -> str | None:
    """Tagged paragraph, or None when tags add nothing (one format) or text already looks like markup."""
    merged: list[Seg] = []
    for t, f in segs:
        if merged and (merged[-1][1] == f or not t.strip()):
            merged[-1] = (merged[-1][0] + t, merged[-1][1])
        elif merged and not merged[-1][0].strip():
            merged[-1] = (merged[-1][0] + t, f)
        else:
            merged.append((t, f))
    if len({f for _, f in merged}) < 2 or HTML_RE.search("".join(t for t, _ in merged)):
        return None
    out = []
    for t, f in merged:
        a = f"a{f.link}" if f.link else ""
        out.append(
            (f"<{a}>" if a else "") + ("<b>" if f.b else "") + ("<i>" if f.i else "")
            + t
            + ("</i>" if f.i else "") + ("</b>" if f.b else "") + (f"</{a}>" if a else "")
        )
    return " ".join("".join(out).split())


def decode(s: str, links: frozenset[int]) -> list[Seg] | None:
    segs: list[Seg] = []
    stack: list[str] = []
    pos = 0

    def add(text: str) -> None:
        if text:
            link = next((int(n[1:]) for n in stack if n[0] == "a"), 0)
            segs.append((text, Fmt("b" in stack, "i" in stack, link)))

    for m in TOKEN_RE.finditer(s):
        add(s[pos : m.start()])
        pos = m.end()
        name = m[2]
        if m[1]:
            if not stack or stack[-1] != name:
                return None
            stack.pop()
            continue
        if name in stack or (m[3] and (int(m[3]) not in links or any(n[0] == "a" for n in stack))):
            return None
        stack.append(name)
    add(s[pos:])
    text = "".join(t for t, _ in segs)
    if stack or not text.strip() or HTML_RE.search(text):
        return None
    return segs
