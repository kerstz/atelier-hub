import json
import sqlite3
import time

from .config import data_dir

FIELDS = ("id", "kind", "title", "status", "gpu", "progress", "message", "output", "error", "created", "started", "finished")
_db: sqlite3.Connection | None = None


def init() -> None:
    global _db
    data_dir().mkdir(parents=True, exist_ok=True)
    _db = sqlite3.connect(data_dir() / "atelier.db", check_same_thread=False)
    _db.row_factory = sqlite3.Row
    _db.execute(
        """create table if not exists jobs(
        id integer primary key autoincrement, kind text, title text, params text,
        status text, gpu integer, progress real default 0, message text default '',
        output text, error text, created real, started real, finished real)"""
    )
    _db.execute(
        """create table if not exists translations(
        id integer primary key autoincrement, created real,
        src text, tgt text, source text, result text)"""
    )
    _db.execute(
        "update jobs set status='failed', error='interrompu', finished=? where status in ('queued','running')",
        (time.time(),),
    )
    _db.commit()


def _row(r: sqlite3.Row | None) -> dict | None:
    return {k: r[k] for k in FIELDS} if r else None


def insert(kind: str, title: str, params: dict, gpu: bool) -> int:
    cur = _db.execute(
        "insert into jobs(kind,title,params,status,gpu,created) values(?,?,?,?,?,?)",
        (kind, title, json.dumps(params), "queued", int(gpu), time.time()),
    )
    _db.commit()
    return cur.lastrowid


def update(jid: int, **f) -> None:
    if not f:
        return
    cols = ",".join(f"{k}=?" for k in f)
    _db.execute(f"update jobs set {cols} where id=?", (*f.values(), jid))
    _db.commit()


def get(jid: int) -> dict | None:
    return _row(_db.execute("select * from jobs where id=?", (jid,)).fetchone())


def params(jid: int) -> dict:
    return json.loads(_db.execute("select params from jobs where id=?", (jid,)).fetchone()[0])


def recent(limit: int = 100) -> list[dict]:
    return [_row(r) for r in _db.execute("select * from jobs order by id desc limit ?", (limit,))]


def active_params(exclude: int | None = None) -> list[dict]:
    rows = _db.execute("select id, params from jobs where status in ('queued','running')")
    return [json.loads(r["params"]) for r in rows if r["id"] != exclude]


def clear_finished() -> None:
    _db.execute("delete from jobs where status in ('done','failed','cancelled')")
    _db.commit()


HISTORY = 20


def add_translation(src: str, tgt: str, source: str, result: str) -> None:
    _db.execute(
        "insert into translations(created,src,tgt,source,result) values(?,?,?,?,?)",
        (time.time(), src, tgt, source, result),
    )
    _db.execute(
        "delete from translations where id not in (select id from translations order by id desc limit ?)",
        (HISTORY,),
    )
    _db.commit()


def recent_translations() -> list[dict]:
    rows = _db.execute("select * from translations order by id desc limit ?", (HISTORY,))
    return [dict(r) for r in rows]


def clear_translations() -> None:
    _db.execute("delete from translations")
    _db.commit()
