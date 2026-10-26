"""Backtesting: run an employee in Shadow mode over past, labelled work and score it against ground truth.

Nothing is executed (no postings, no emails, no refunds); the employee only says what it WOULD have done.
How a template is evaluated is part of the template (`evaluation:`):
  files  — a folder of documents + a labels file (e.g. last month's invoices)
  cases  — case folders whose labels.json marks the history set
  shadow — no ground truth: a dry run over the current intake, reviewed by a manager
This evidence is what earns an employee its autonomy."""

import json
import time

from .. import company as co
from .. import db
from ..config import DATA_DIR
from ..core.runner import MemoryRecorder, Runner
from . import packs, work

POSTED = ("auto_post", "approval")


def start(emp: dict) -> str:
    bt = {
        "id": db.new_id("bt"),
        "employee_id": emp["id"],
        "status": "running",
        "progress": 0.0,
        "n_tasks": 0,
        "route_accuracy": None,
        "per_issue": [],
        "hours_saved": 0,
        "money_saved_inr": 0,
        "ai_calls": 0,
        "duration_s": 0,
        "rows": [],
        "plan_version": emp["plan_version"],
    }
    db.put("backtests", bt)
    work.POOL.submit(_run, bt["id"], emp["id"])
    return bt["id"]


def _items(emp: dict) -> tuple[str, list[dict]]:
    """(evaluation type, [{task, label}]) for this employee's template."""
    ev = (packs.get(emp["role"]) or {}).get("evaluation") or {"type": "shadow"}
    if ev["type"] == "files":
        labels = json.loads((DATA_DIR / ev["labels"]).read_text(encoding="utf-8"))
        return "files", [{"task": {"file": lab["file"], "title": lab["file"]}, "label": lab} for lab in labels]
    if ev["type"] == "cases":
        rows = work.case_labels(ev["path"], "history")
        return "cases", [
            {"task": {"case_id": r["case_id"], "folder": r["folder"], "title": r["title"]}, "label": r} for r in rows
        ]
    intake = emp.get("intake") or {}
    if intake.get("type") == "ledger":
        key = intake.get("key", "id")
        return "shadow", [
            {"task": {key: r[key], "title": str(r.get("name", r[key]))}, "label": None}
            for r in co.ledger(intake["path"])
        ]
    return "shadow", []


def _run(bt_id: str, emp_id: str) -> None:
    emp = db.must("employees", emp_id)
    # replay: score the decisions only — drafting letters nobody will send would just spend Gemma calls
    settings = work.settings() | {"chaos_mode": False, "replay": True}
    minutes = settings.get("minutes_per_case_manual", 20)
    t0 = time.time()
    try:
        kind, items = _items(emp)
        carry_seen = ((packs.get(emp["role"]) or {}).get("evaluation") or {}).get("carry_seen")
        issue_types = sorted({i for it in items if it["label"] for i in it["label"].get("expected_issues", [])})
        seen: list = []
        rows, calls, hours = [], 0, 0.0
        for i, it in enumerate(items):
            task = {"id": f"{bt_id}_{i}", "thread_id": f"{bt_id}_{i}", **it["task"]}
            Runner(
                emp["plan"],
                emp,
                task,
                settings,
                mode="shadow",
                recorder=MemoryRecorder(task),
                seen=seen if carry_seen else None,
            ).start()
            ref, lab = task.get("ref") or {}, it["label"]
            pred = (task.get("outcome") or {}).get("route") or "human_review"
            if carry_seen and pred in POSTED and ref.get("invoice"):
                inv = ref["invoice"]
                seen.append(
                    {
                        "vendor_id": ref.get("vendor_id"),
                        "vendor_name": inv.get("vendor_name"),
                        "invoice_no": inv.get("invoice_no"),
                        "total": inv.get("total"),
                        "invoice_date": inv.get("invoice_date"),
                    }
                )
            calls += int(task.get("ai_calls") or 0)
            hours += (0.5 if pred == "human_review" else 1.0) * minutes / 60
            row = {
                "file": task.get("case_id") or task.get("file") or task.get("title"),
                "vendor": (ref.get("invoice") or {}).get("vendor_name") or task.get("title"),
                "total": (lab or {}).get("total"),
                "predicted_route": pred,
                "found_issues": sorted(
                    {f["type"] for f in task.get("flags", []) if not issue_types or f["type"] in issue_types}
                ),
                "ai_calls": task.get("ai_calls", 0),
            }
            if lab:
                row.update(
                    expected_route=lab["expected_route"],
                    expected_issues=sorted(lab.get("expected_issues", [])),
                    correct=pred in (lab.get("acceptable_routes") or [lab["expected_route"]]),
                    category_expected=lab.get("category"),
                    category_predicted=ref.get("category"),
                )
            else:
                row.update(expected_route="—", expected_issues=[], correct=True)
            rows.append(row)
            db.update("backtests", bt_id, progress=round((i + 1) / len(items), 3), n_tasks=i + 1, rows=rows)
        per_issue = []
        for t in issue_types:
            tp = sum(t in r["expected_issues"] and t in r["found_issues"] for r in rows)
            fp = sum(t not in r["expected_issues"] and t in r["found_issues"] for r in rows)
            fn = sum(t in r["expected_issues"] and t not in r["found_issues"] for r in rows)
            per_issue.append(
                {
                    "type": t,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                }
            )
        acc = (sum(r["correct"] for r in rows) / len(rows)) if rows and kind != "shadow" else None
        db.update(
            "backtests",
            bt_id,
            status="done",
            progress=1.0,
            kind=kind,
            route_accuracy=round(acc, 3) if acc is not None else None,
            per_issue=per_issue,
            hours_saved=round(hours, 1),
            money_saved_inr=round(hours * settings["hourly_cost_inr"]),
            ai_calls=calls,
            duration_s=round(time.time() - t0, 1),
            rows=rows,
        )
        db.audit(
            emp["name"],
            "backtest",
            f"{len(rows)} items ({kind})" + (f", route accuracy {acc:.0%}" if acc is not None else ""),
        )
    except Exception as e:
        db.update("backtests", bt_id, status="error", error=str(e))


def summary(bt: dict, with_rows: bool = True) -> dict:
    out = dict(bt)
    if not with_rows:
        out.pop("rows", None)
    return out
