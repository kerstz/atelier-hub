import copy
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import unquote

from lxml import etree

from . import inline
from .inline import Fmt, Seg

BLOCK = {
    "html", "body", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody",
    "tfoot", "tr", "td", "th", "caption", "blockquote", "figure", "figcaption", "section", "article", "aside", "nav", "header",
    "footer", "main", "address", "details", "summary", "fieldset", "form", "hr", "title",
}
OPAQUE = {"pre", "script", "style", "head", "svg", "math"}
ATOM = {"br", "img", "wbr", "code", "kbd", "samp", "var", "tt", "svg", "math", "image", "hr", "input", "audio", "video", "object"}
BOLD, ITAL = {"b", "strong"}, {"i", "em"}
LETTER_RE = re.compile(r"[^\W\d_]")
MARK_RE = re.compile(r"⟦(\d+)⟧")
SPLIT_RE = re.compile(r"(⟦\d+⟧)")
NS_OPF = "http://www.idpf.org/2007/opf"
NS_CONT = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_NCX = "http://www.daisy.org/z3986/2005/ncx/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

def flat(t: str) -> str:
    return " ".join(t.split())


Translate = Callable[[list[str]], Awaitable[dict[str, str]]]


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def text_of(el) -> str:
    return "".join(el.itertext())


@dataclass
class Run:
    owner: object          # element whose .text / .tail leads the run
    attr: str              # "text" | "tail"
    children: list = field(default_factory=list)
    tagged: str | None = None
    plain: str = ""
    links: dict[int, object] = field(default_factory=dict)
    atoms: dict[int, object] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=lambda: {"b": "strong", "i": "em"})
    lead: str = ""
    trail: str = ""
    single: Fmt = Fmt()


def collect(el, out: list[Run]) -> None:
    cur = Run(el, "text")

    def flush() -> None:
        if (getattr(cur.owner, cur.attr) or cur.children) and has_letters(cur):
            out.append(cur)

    for child in el:
        if not isinstance(child.tag, str):          # comment / PI keep their tail in the flow
            cur.children.append(child)
            continue
        name = local(child)
        if name in OPAQUE or name in BLOCK:
            flush()
            if name in BLOCK and name not in OPAQUE:
                collect(child, out)
            cur = Run(child, "tail")
        else:
            cur.children.append(child)
    flush()


def has_letters(run: Run) -> bool:
    t = getattr(run.owner, run.attr) or ""
    t += "".join(text_of(c) + (c.tail or "") for c in run.children if isinstance(c.tag, str) and local(c) not in ATOM)
    return bool(LETTER_RE.search(t))


def encode_run(run: Run) -> None:
    segs: list[Seg] = []
    nlink = natom = 0

    def add(t: str | None, f: Fmt) -> None:
        if t:
            segs.append((t, f))

    def atom(el, f: Fmt) -> None:
        nonlocal natom
        natom += 1
        c = copy.deepcopy(el)
        c.tail = None
        run.atoms[natom] = c
        add(f"⟦{natom}⟧", f)

    def walk(el, f: Fmt) -> None:
        nonlocal nlink
        if not isinstance(el.tag, str):
            add(el.tail, f)
            return
        name = local(el)
        body = text_of(el)
        if name in ATOM or (name not in BOLD | ITAL and not LETTER_RE.search(body)):
            atom(el, f)
        elif name in BOLD or name in ITAL:
            run.names["b" if name in BOLD else "i"] = name
            inner(el, f._replace(b=f.b or name in BOLD, i=f.i or name in ITAL))
        elif f.link or (name != "a" and any(local(d) == "a" for d in el.iterdescendants() if isinstance(d.tag, str))):
            inner(el, f)               # nested slot: outer wrapper dropped, inner link / flat text wins
        else:
            nlink += 1
            c = copy.deepcopy(el)
            for k in list(c):
                c.remove(k)
            c.text = c.tail = None
            run.links[nlink] = c
            inner(el, f._replace(link=nlink))
        add(el.tail, f)

    def inner(el, f: Fmt) -> None:
        add(el.text, f)
        for k in el:
            walk(k, f)

    add(getattr(run.owner, run.attr), Fmt())
    for c in run.children:
        walk(c, Fmt())
    raw = "".join(t for t, _ in segs)
    run.lead = " " if raw[:1].isspace() else ""
    run.trail = " " if raw[-1:].isspace() else ""
    run.plain = flat(raw)
    run.tagged = inline.encode(segs)
    fm = [f for t, f in segs if t.strip() and not MARK_RE.fullmatch(t.strip())]
    run.single = fm[0] if fm else Fmt()


def fix_markers(text: str, ids: set[int]) -> str:
    seen: set[int] = set()

    def sub(m):
        n = int(m[1])
        if n in ids and n not in seen:
            seen.add(n)
            return m[0]
        return ""

    text = MARK_RE.sub(sub, text)
    return (text + "".join(f"⟦{n}⟧" for n in sorted(ids - seen))).strip()


def markers_ok(text: str, ids: set[int]) -> bool:
    found = [int(m) for m in MARK_RE.findall(text)]
    return sorted(found) == sorted(ids)


def rebuild(run: Run, segs: list[Seg]) -> None:
    owner, attr = run.owner, run.attr
    parent = owner if attr == "text" else owner.getparent()
    for c in run.children:
        parent.remove(c)
    setattr(owner, attr, None)
    pos = 0 if attr == "text" else parent.index(owner) + 1
    last = None

    def text(t: str) -> None:
        if last is None:
            setattr(owner, attr, (getattr(owner, attr) or "") + t)
        else:
            last.tail = (last.tail or "") + t

    def append(el) -> None:
        nonlocal pos, last
        el.tail = None
        parent.insert(pos, el)
        pos += 1
        last = el

    groups: list[list] = []
    for t, f in segs:
        if groups and groups[-1][0] == f:
            groups[-1][1] += t
        else:
            groups.append([f, t])
    if run.lead:
        text(" ")
    for f, body in groups:
        outer = chain = copy.deepcopy(run.links[f.link]) if f.link else None
        for flag, key in ((f.b, "b"), (f.i, "i")):
            if not flag:
                continue
            w = etree.Element(_qname(owner, run.names[key]))
            if chain is None:
                outer = chain = w
            else:
                chain.append(w)
                chain = w
        for part in SPLIT_RE.split(body):
            if not part:
                continue
            m = MARK_RE.fullmatch(part)
            node = copy.deepcopy(run.atoms[int(m[1])]) if m else None
            if chain is None:
                text(part) if node is None else append(node)
            elif node is not None:
                chain.append(node)
            elif len(chain):
                chain[-1].tail = (chain[-1].tail or "") + part
            else:
                chain.text = (chain.text or "") + part
        if outer is not None:
            append(outer)
    if run.trail:
        text(" ")


def _qname(ref, name: str) -> str:
    ns = etree.QName(ref).namespace
    return f"{{{ns}}}{name}" if ns else name


# ---- package

def _parse(data: bytes):
    try:
        return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError:
        return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, recover=True))


def _dump(root, orig: bytes) -> bytes:
    doctype = None
    m = re.search(rb"<!DOCTYPE[^>]*>", orig)
    if m:
        doctype = m[0].decode("utf-8", "replace")
    return etree.tostring(root, xml_declaration=True, encoding="utf-8", doctype=doctype)


@dataclass
class Doc:
    name: str
    data: bytes
    root: object
    kind: str                       # "xhtml" | "ncx" | "opf"
    runs: list[Run] = field(default_factory=list)
    plain: list[tuple[object, str]] = field(default_factory=list)   # (element, text) translated flat


def package(z: zipfile.ZipFile) -> tuple[str, object]:
    cont = _parse(z.read("META-INF/container.xml"))
    rf = cont.find(f".//{{{NS_CONT}}}rootfile")
    if rf is None:
        raise RuntimeError("EPUB invalide: container.xml")
    path = rf.get("full-path")
    return path, _parse(z.read(path))


def load(src: Path) -> tuple[list[Doc], zipfile.ZipFile]:
    z = zipfile.ZipFile(src)
    opf_path, opf = package(z)
    base = posixpath.dirname(opf_path)
    items = {i.get("id"): i for i in opf.iter(f"{{{NS_OPF}}}item")}
    order = [items[r.get("idref")] for r in opf.iter(f"{{{NS_OPF}}}itemref") if r.get("idref") in items]
    rest = [i for i in items.values() if i not in order]
    docs: list[Doc] = []
    names = set(z.namelist())
    seen: set[str] = set()
    for it in order + rest:
        href = posixpath.normpath(posixpath.join(base, unquote((it.get("href") or "").split("#")[0])))
        mt = it.get("media-type")
        if href in seen or href not in names or mt not in ("application/xhtml+xml", "application/x-dtbncx+xml", "text/html"):
            continue
        seen.add(href)
        data = z.read(href)
        root = _parse(data)
        if mt == "application/x-dtbncx+xml":
            d = Doc(href, data, root, "ncx")
            d.plain = [(t, text_of(t)) for t in root.iter(f"{{{NS_NCX}}}text") if LETTER_RE.search(text_of(t))]
        else:
            d = Doc(href, data, root, "xhtml")
            collect(root, d.runs)
            for t in root.iter("{*}title"):
                if t.getparent() is not None and local(t.getparent()) == "head" and LETTER_RE.search(text_of(t)):
                    d.plain.append((t, text_of(t)))
            for r in d.runs:
                encode_run(r)
        docs.append(d)
    meta = Doc(opf_path, b"", opf, "opf")
    for tag in ("title", "description"):
        meta.plain += [(e, text_of(e)) for e in opf.iter(f"{{{NS_DC}}}{tag}") if LETTER_RE.search(text_of(e))]
    docs.append(meta)
    return docs, z


async def translate_epub(src: Path, dest: Path, tgt: str, translate: Translate, on_stage: Callable[[str], None] | None = None) -> int:
    """Translate EPUB `src` into `dest`. `translate` maps unique strings -> translations."""
    docs, z = load(src)
    runs = [r for d in docs for r in d.runs]
    if not runs and not any(d.plain for d in docs):
        raise RuntimeError("aucun texte à traduire")
    texts = [r.tagged or r.plain for r in runs] + [t for d in docs for _, t in d.plain]
    done = await translate([flat(t) for t in texts])
    retry: list[Run] = []
    for r, t in zip(runs, texts):
        out = done[flat(t)]
        ids = set(r.atoms)
        segs = None
        if r.tagged:
            segs = inline.decode(out, frozenset(r.links))
            if segs and not markers_ok("".join(s for s, _ in segs), ids):
                segs = None
        elif markers_ok(out, ids):
            segs = [(out, r.single)]
        if segs:
            rebuild(r, segs)
        else:
            retry.append(r)
    if retry:
        again = await translate([r.plain for r in retry])
        for r in retry:
            rebuild(r, [(fix_markers(again[r.plain], set(r.atoms)), Fmt())])
    k = len(runs)
    for d in docs:
        for el, t in d.plain:
            new = done[flat(texts[k])]
            k += 1
            for c in list(el):
                el.remove(c)
            el.text = new
    for d in docs:
        if d.kind == "opf":
            for e in d.root.iter(f"{{{NS_DC}}}language"):
                e.text = tgt
        elif d.kind == "xhtml":
            for e in d.root.iter("{*}html"):
                for a in ("lang", XML_LANG):
                    if e.get(a) is not None:
                        e.set(a, tgt)
    new = {d.name: _dump(d.root, d.data) for d in docs}
    with zipfile.ZipFile(dest, "w") as out:
        for info in sorted(z.infolist(), key=lambda i: i.filename != "mimetype"):
            data = new.get(info.filename, z.read(info.filename))
            ct = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            out.writestr(zipfile.ZipInfo(info.filename, info.date_time), data, ct)
    z.close()
    return len(runs)
