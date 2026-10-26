"""A tiny thread-safe JSON document store on SQLite.

Collections (employees, tasks, inbox, backtests, drafts, outputs) are stored as JSON documents.
Events, audit log, corrections and plan versions get their own simple tables.
"""

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from .config import STATE_DIR

_DB_PATH = STATE_DIR / "prompt2process.sqlite"
_lock = threading.RLock()
_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def init() -> None:
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs(
                coll TEXT, id TEXT, employee_id TEXT, status TEXT,
                created_at TEXT, updated_at TEXT, data TEXT, PRIMARY KEY (coll, id));
            CREATE INDEX IF NOT EXISTS docs_coll ON docs(coll, employee_id, status);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts TEXT, level TEXT, message TEXT, step_id TEXT);
            CREATE INDEX IF NOT EXISTS events_task ON events(task_id);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, task_id TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS corrections(
                id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, task_id TEXT, field TEXT,
                value TEXT, text TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS plan_versions(
                employee_id TEXT, version INTEGER, created_at TEXT, note TEXT, plan TEXT,
                PRIMARY KEY (employee_id, version));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            """
        )
        _conn.commit()


# ---------------------------------------------------------------- documents
def put(coll: str, doc: dict) -> dict:
    """Insert or replace a document. Needs doc['id']."""
    with _lock:
        doc.setdefault("created_at", now())
        doc["updated_at"] = now()
        _conn.execute(
            "INSERT OR REPLACE INTO docs(coll,id,employee_id,status,created_at,updated_at,data) VALUES (?,?,?,?,?,?,?)",
            (
                coll,
                doc["id"],
                doc.get("employee_id"),
                doc.get("status"),
                doc["created_at"],
                doc["updated_at"],
                json.dumps(doc, default=str),
            ),
        )
        _conn.commit()
        return doc


def get(coll: str, doc_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT data FROM docs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
        return json.loads(row["data"]) if row else None


def must(coll: str, doc_id: str) -> dict:
    """Like get(), but the document must exist."""
    doc = get(coll, doc_id)
    if doc is None:
        raise LookupError(f"{coll}/{doc_id} not found")
    return doc


def update(coll: str, doc_id: str, **changes) -> dict | None:
    with _lock:
        doc = get(coll, doc_id)
        if doc is None:
            return None
        doc.update(changes)
        return put(coll, doc)


def mutate(coll: str, doc_id: str, fn) -> dict | None:
    """Read-modify-write under the lock. fn(doc) edits the doc in place."""
    with _lock:
        doc = get(coll, doc_id)
        if doc is None:
            return None
        fn(doc)
        return put(coll, doc)


def query(coll: str, employee_id: str | None = None, status: str | None = None, limit: int = 1000) -> list[dict]:
    sql = "SELECT data FROM docs WHERE coll=?"
    args: list[str | int] = [coll]
    if employee_id:
        sql += " AND employee_id=?"
        args.append(employee_id)
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    args.append(limit)
    with _lock:
        return [json.loads(r["data"]) for r in _conn.execute(sql, args).fetchall()]


def delete(coll: str, doc_id: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, doc_id))
        _conn.commit()


# ---------------------------------------------------------------- events / audit
def event(task_id: str, level: str, message: str, step_id: str | None = None) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO events(task_id,ts,level,message,step_id) VALUES (?,?,?,?,?)",
            (task_id, now(), level, message, step_id),
        )
        _conn.commit()


def events(task_id: str | None = None, limit: int = 500) -> list[dict]:
    with _lock:
        if task_id:
            rows = _conn.execute(
                "SELECT * FROM events WHERE task_id=? ORDER BY id LIMIT ?", (task_id, limit)
            ).fetchall()
        else:
            rows = _conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{k: r[k] for k in ("ts", "level", "message", "step_id", "task_id")} for r in rows]


def audit(actor: str, action: str, detail: str, task_id: str | None = None) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO audit(ts,actor,action,task_id,detail) VALUES (?,?,?,?,?)",
            (now(), actor, action, task_id, detail),
        )
        _conn.commit()


def audit_log(limit: int = 100) -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{k: r[k] for k in ("ts", "actor", "action", "task_id", "detail")} for r in rows]


# ---------------------------------------------------------------- corrections
def add_correction(employee_id: str, task_id: str, field: str, value: str, text: str) -> int:
    with _lock:
        _conn.execute(
            "INSERT INTO corrections(employee_id,task_id,field,value,text,created_at) VALUES (?,?,?,?,?,?)",
            (employee_id, task_id, field, str(value), text, now()),
        )
        _conn.commit()
        return _conn.execute("SELECT COUNT(*) c FROM corrections WHERE employee_id=?", (employee_id,)).fetchone()["c"]


def corrections(employee_id: str, field: str | None = None) -> list[dict]:
    with _lock:
        sql, args = "SELECT * FROM corrections WHERE employee_id=?", [employee_id]
        if field:
            sql += " AND field=?"
            args.append(field)
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


# ---------------------------------------------------------------- plan versions
def save_plan_version(employee_id: str, plan: dict, note: str) -> int:
    with _lock:
        row = _conn.execute("SELECT MAX(version) v FROM plan_versions WHERE employee_id=?", (employee_id,)).fetchone()
        version = (row["v"] or 0) + 1
        _conn.execute(
            "INSERT INTO plan_versions VALUES (?,?,?,?,?)", (employee_id, version, now(), note, json.dumps(plan))
        )
        _conn.commit()
        return version


def plan_versions(employee_id: str) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM plan_versions WHERE employee_id=? ORDER BY version DESC", (employee_id,)
        ).fetchall()
        return [
            {"version": r["version"], "created_at": r["created_at"], "note": r["note"], "plan": json.loads(r["plan"])}
            for r in rows
        ]


# ---------------------------------------------------------------- settings
def get_settings(defaults: dict) -> dict:
    with _lock:
        out = dict(defaults)
        for r in _conn.execute("SELECT key, value FROM settings").fetchall():
            out[r["key"]] = json.loads(r["value"])
        return out


def set_settings(changes: dict) -> None:
    with _lock:
        for k, v in changes.items():
            _conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, json.dumps(v)))
        _conn.commit()


init()
