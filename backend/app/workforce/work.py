"""The work loop: ingest new work, run queues in the background, resume after approvals, close reviews."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import company as co
from .. import db
from ..config import DATA_DIR
from ..core.registry import REGISTRY, ExecContext
from ..core.runner import DBRecorder, Runner
from ..learning import classifier
from . import employees, healing, packs

POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="p2p-work")
_emp_locks: dict[str, threading.Lock] = {}


def settings() -> dict:
    from ..config import DEFAULT_SETTINGS

    return db.get_settings(DEFAULT_SETTINGS)


def _lock(emp_id: str) -> threading.Lock:
    return _emp_locks.setdefault(emp_id, threading.Lock())


def _new_task(emp: dict, kind: str, title: str, **extra) -> dict:
    t = {
        "id": db.new_id("tsk"),
        "employee_id": emp["id"],
        "kind": kind,
        "title": title,
        "status": "queued",
        "mode": "live",
        "plan_version": emp["plan_version"],
        "plan": emp["plan"],
        "fields": {},
        "flags": [],
        "steps": [],
        "ai_calls": 0,
        "duration_s": None,
        "outcome": {},
        "runs": 0,
    }
    t.update(extra)
    db.put("tasks", t)
    return t


def ingest(emp: dict) -> list[dict]:
    """Pull new work from the employee's intake channel (configured per employee, defined by its template)."""
    intake = emp.get("intake") or {}
    kind, path = intake.get("type"), intake.get("path", "")
    existing = db.query("tasks", employee_id=emp["id"], limit=5000)
    created = []
    if kind in ("folder", "upload"):
        have = {t.get("file") for t in existing}
        folder = DATA_DIR / path
        for p in sorted(folder.rglob(intake.get("pattern", "*.pdf"))) if folder.exists() else []:
            rel = str(p.relative_to(DATA_DIR)).replace("\\", "/")
            if rel not in have:
                created.append(_new_task(emp, "document", p.stem.replace("_", " "), file=rel, source_file=rel))
    elif kind == "ledger":
        key = intake.get("key", "id")
        have = {t.get(key) for t in existing}
        for row in co.ledger(path):
            if row.get(key) and row[key] not in have:
                title = intake.get("title", "{" + key + "}").format_map(_Safe(row))
                created.append(_new_task(emp, "record", title, **{key: row[key]}))
    elif kind == "cases":
        have = {t.get("case_id") for t in existing}
        labels = {r["case_id"]: r for r in case_labels(path)}
        base = DATA_DIR / path
        for folder in sorted(f for f in base.iterdir() if f.is_dir()) if base.exists() else []:
            lab = labels.get(folder.name, {})
            if folder.name in have or lab.get("set") == "history":  # labelled history is for backtests
                continue
            files = sorted(str(f.relative_to(DATA_DIR)).replace("\\", "/") for f in folder.iterdir())
            first_pdf = next((f for f in files if f.endswith(".pdf")), None)
            created.append(
                _new_task(
                    emp,
                    "case",
                    lab.get("title", folder.name),
                    case_id=folder.name,
                    folder=str(folder.relative_to(DATA_DIR)).replace("\\", "/"),
                    files=files,
                    file=first_pdf,
                    source_file=first_pdf,
                )
            )
    if created:
        db.audit(emp["name"], "ingested", f"{len(created)} new task(s) from {kind} intake '{path}'")
    return created


class _Safe(dict):
    def __missing__(self, key):
        return ""


def case_labels(path: str, set_: str | None = None) -> list[dict]:
    """Ground-truth labels that ship with a case folder (used for backtests; optional)."""
    import json

    f = DATA_DIR / path / "labels.json"
    rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    return [r for r in rows if set_ is None or r.get("set") == set_]


def add_upload(emp: dict, filename: str, data: bytes) -> dict:
    folder = DATA_DIR / "inbox" / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-") or "upload.pdf"
    path = folder / safe
    path.write_bytes(data)
    rel = str(path.relative_to(DATA_DIR))
    return _new_task(emp, "invoice", Path(safe).stem, file=rel, source_file=rel)


def _execute(task_id: str, resume: dict | None = None) -> str:
    task = db.must("tasks", task_id)
    emp = db.must("employees", task["employee_id"])
    rec = DBRecorder(task_id)
    t0 = time.time()
    runner = Runner(task["plan"], emp, rec.task, settings(), mode="live", recorder=rec)
    try:
        status = runner.resume(resume) if resume else runner.start()
    except Exception as e:
        rec.event("error", f"Task crashed: {e}")
        rec.status("failed")
        return "failed"
    rec.task["duration_s"] = round((rec.task.get("duration_s") or 0) + time.time() - t0, 1)
    rec.save()
    return status


def run_queue(emp_id: str, task_ids: list[str] | None = None) -> int:
    queued = list(db.query("tasks", employee_id=emp_id, status="queued", limit=500))
    if task_ids:
        queued = [t for t in queued if t["id"] in task_ids]
    queued.sort(key=lambda t: t["created_at"])

    def work():
        with _lock(emp_id):
            for t in queued:
                fresh = db.get("tasks", t["id"])
                if fresh and fresh["status"] == "queued":
                    _execute(t["id"])

    if queued:
        POOL.submit(work)
    return len(queued)


def _ctx(task: dict, emp: dict) -> ExecContext:
    return ExecContext(task=task, employee=emp, settings=settings(), mode="live", step_id="human")


def decide(item_id: str, decision: str, note: str = "", edits: dict | None = None, by: str = "Manager") -> dict:
    item = db.get("inbox", item_id)
    if not item or item["status"] != "open":
        raise ValueError("inbox item not found or already decided")
    emp = db.must("employees", item["employee_id"])
    task = db.get("tasks", item["task_id"]) if item.get("task_id") else None
    item["status"] = "done"
    item["decision"] = {"decision": decision, "note": note, "by": by, "at": db.now()}
    db.put("inbox", item)
    db.audit(by, f"{item['kind']}_{decision}", f"{item['title']} {('— ' + note) if note else ''}", item.get("task_id"))

    if edits and task and "category" in edits:
        correct(task["id"], "category", edits["category"], by=by)
        task = db.get("tasks", task["id"])

    if item["kind"] == "approval" and task:
        if decision == "approve" and int(emp.get("autonomy_level", 0)) == 1:
            db.mutate(
                "employees",
                emp["id"],
                lambda e: e.update(supervised_approvals=int(e.get("supervised_approvals", 0)) + 1),
            )
        POOL.submit(_execute, task["id"], {"decision": decision, "note": note, "by": by})

    elif item["kind"] == "review" and task:
        _close_review(task, emp, decision, note, by)

    elif item["kind"] == "healing":
        if decision == "approve":
            new_plan = healing.apply(emp["plan"], item["payload"]["patch"])
            emp, report = employees.save_plan(emp, new_plan, f"self-healing fix for {item['payload']['step_id']}")
            if report["ok"]:
                for tid in item["payload"].get("task_ids", []):
                    t = db.get("tasks", tid)
                    if t and t["status"] == "failed":
                        t.update(
                            status="queued",
                            plan=emp["plan"],
                            plan_version=emp["plan_version"],
                            steps=[],
                            flags=[],
                            fields={},
                            runs=int(t.get("runs", 0)) + 1,
                            thread_id=f"{tid}:r{int(t.get('runs', 0)) + 1}",
                        )
                        db.put("tasks", t)
                run_queue(emp["id"])
    return {"ok": True}


def _close_review(task: dict, emp: dict, decision: str, note: str, by: str) -> None:
    ref = task.get("ref") or {}
    ctx = _ctx(task, emp)
    if emp["role"] == "ap":
        inv = ref.get("invoice") or {}
        if decision == "approve":
            cat = (
                ((task.get("fields") or {}).get("category") or {}).get("value")
                or ref.get("category")
                or "Uncategorised"
            )
            post: dict = next((s for s in task["plan"]["steps"] if s["action"] == "post_journal_entry"), {})
            REGISTRY["post_journal_entry"].fn(
                ctx,
                invoice=inv,
                vendor_id=ref.get("vendor_id"),
                category=cat,
                inventory_categories=(post.get("params") or {}).get("inventory_categories"),
            )
            if ref.get("vendor_id"):
                REGISTRY["add_to_payment_batch"].fn(ctx, invoice=inv, vendor_id=ref["vendor_id"])
            outcome = {"route": "human_review", "final_decision": "posted", "summary": f"Posted after review by {by}"}
        else:
            REGISTRY["reject_invoice"].fn(ctx, invoice=inv, reason=note or "Rejected after manual review")
            outcome = {
                "route": "human_review",
                "final_decision": "rejected",
                "summary": f"Rejected after review by {by}",
            }
    elif p := packs.get(emp["role"]):
        draft = ref.get("draft") or {}
        contact = (p.get("contact") or {}).get("email", "")
        to = (
            ((ref.get("case_fields") or {}).get(contact.split(".")[0]) or {}).get(contact.split(".")[-1])
            if contact
            else None
        )
        if decision == "approve":
            REGISTRY["record_outcome"].fn(
                ctx,
                case_id=task.get("case_id", ""),
                outcome="approved_after_review",
                summary=f"Approved by {by} after review. {note}".strip(),
            )
            if draft and to:
                REGISTRY["send_message"].fn(ctx, to=to, subject=draft.get("subject", ""), body=draft.get("body", ""))
            outcome = {
                "route": "human_review",
                "final_decision": "approved_after_review",
                "summary": f"Approved by {by} after review",
            }
        else:
            REGISTRY["record_outcome"].fn(
                ctx,
                case_id=task.get("case_id", ""),
                outcome="rejected_after_review",
                summary=f"Rejected by {by} after review. {note}".strip(),
            )
            outcome = {
                "route": "human_review",
                "final_decision": "rejected",
                "summary": f"Rejected by {by} after review",
            }
    else:
        draft = ref.get("draft") or {}
        cust = ref.get("customer") or {}
        if decision == "approve" and draft:
            REGISTRY["send_reminder"].fn(
                ctx, to=cust.get("email", ""), subject=draft.get("subject", ""), body=draft.get("body", "")
            )
            REGISTRY["log_followup"].fn(ctx, customer_id=cust.get("customer_id", ""), level=ref.get("level", 1))
            outcome = {
                "route": f"level_{ref.get('level')}",
                "final_decision": "reminder_sent",
                "summary": f"Sent after review by {by}",
            }
        else:
            outcome = {
                "route": f"level_{ref.get('level')}",
                "final_decision": "rejected",
                "summary": f"Held by {by}: {note}",
            }
    db.mutate(
        "tasks", task["id"], lambda t: t.update(status="done" if decision == "approve" else "rejected", outcome=outcome)
    )
    db.event(task["id"], "success", f"Review closed by {by}: {outcome['summary']}")


def correct(task_id: str, field: str, value, by: str = "Manager") -> int:
    task = db.must("tasks", task_id)
    ref = task.get("ref") or {}
    text = ref.get("category_text") or classifier.invoice_text(
        (ref.get("invoice") or {}).get("vendor_name"), (ref.get("invoice") or {}).get("line_items")
    )
    n = db.add_correction(task["employee_id"], task_id, field, value, text)

    def upd(t):
        before = ((t.get("fields") or {}).get(field) or {}).get("value")
        t.setdefault("fields", {})[field] = {"value": value, "confidence": 1.0, "source": "human", "before": before}

    db.mutate("tasks", task_id, upd)
    db.audit(by, "corrected", f"{field} → {value}", task_id)
    return n
