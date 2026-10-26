"""Digital employees: hiring from a template or a custom SOP, plan versions, KPIs and earned autonomy.

Nothing here knows about specific employees, companies or sectors — titles, sectors, colours, intake channels
and approver roles all come from the template the employee was hired from (or from the custom SOP).
"""

from .. import config, db
from ..core import checker
from ..core.registry import REGISTRY
from . import packs

LEVELS = {0: "Shadow", 1: "Supervised", 2: "Autonomous"}
CUSTOM = {
    "sector": "Custom",
    "department": "Custom process",
    "role_title": "Digital employee",
    "avatar_color": "#6B7280",
}


def role_meta(role: str) -> dict:
    """Sector, department, title and colour for a role — read from its template."""
    p = packs.get(role)
    if not p:
        return dict(CUSTOM)
    return {
        "sector": p["sector"],
        "department": p["department"],
        "role_title": p["employee"]["title"],
        "avatar_color": p["employee"].get("color", "#6B7280"),
    }


def tools_for(role: str) -> list[str]:
    return sorted(n for n, s in REGISTRY.items() if s.allowed(role))


def create(
    name: str,
    role: str,
    plan: dict,
    sop_title: str,
    note: str = "Hired from SOP",
    intake: dict | None = None,
    parameters: dict | None = None,
) -> dict:
    report, normalised = checker.check(plan, role)
    if not report["ok"] or normalised is None:
        raise ValueError("plan does not pass the checker: " + "; ".join(report["errors"][:5]))
    p = packs.get(role) or {}
    emp = {
        "id": db.new_id("emp"),
        "name": name.strip(),
        "role": role,
        "template_id": p.get("id"),
        **role_meta(role),
        "avatar_initials": "".join(w[0] for w in name.split()[:2]).upper(),
        "autonomy_level": 0,
        "intake": intake or p.get("intake") or {"type": "upload", "path": "uploads"},
        "parameters": {**(p.get("parameters") or {}), **(parameters or {})},
        "tools": tools_for(role),
        "plan": normalised,
        "sop_title": sop_title,
        "status": "active",
        "supervised_approvals": 0,
    }
    emp["plan_version"] = db.save_plan_version(emp["id"], normalised, note)
    db.put("employees", emp)
    db.audit("manager", "hired", f"{emp['name']} as {emp['role_title']} — {emp['sector']} (starts in Shadow mode)")
    return emp


def save_plan(emp: dict, plan: dict, note: str) -> tuple[dict, dict]:
    report, normalised = checker.check(plan, emp["role"], emp.get("tools"))
    if report["ok"] and normalised is not None:
        emp["plan"] = normalised
        emp["plan_version"] = db.save_plan_version(emp["id"], normalised, note or "edited")
        db.put("employees", emp)
        db.audit("manager", "plan_updated", f"{emp['name']} plan v{emp['plan_version']}: {note}")
    return emp, report


def diff(a: dict, b: dict) -> list[dict]:
    sa = {s["id"]: s for s in a["steps"]}
    sb = {s["id"]: s for s in b["steps"]}
    out = []
    for sid in sa.keys() - sb.keys():
        out.append({"step_id": sid, "kind": "removed", "before": sa[sid].get("title")})
    for sid in sb.keys() - sa.keys():
        out.append({"step_id": sid, "kind": "added", "after": sb[sid].get("title")})
    for sid in sa.keys() & sb.keys():
        for field in ("title", "action", "when", "requires_approval"):
            if sa[sid].get(field) != sb[sid].get(field):
                out.append(
                    {
                        "step_id": sid,
                        "kind": "changed",
                        "field": field,
                        "before": sa[sid].get(field),
                        "after": sb[sid].get(field),
                    }
                )
        for k in set(sa[sid].get("params", {})) | set(sb[sid].get("params", {})):
            if sa[sid].get("params", {}).get(k) != sb[sid].get("params", {}).get(k):
                out.append(
                    {
                        "step_id": sid,
                        "kind": "changed",
                        "field": f"params.{k}",
                        "before": sa[sid].get("params", {}).get(k),
                        "after": sb[sid].get("params", {}).get(k),
                    }
                )
        for k in ("retry", "fallback"):
            if (sa[sid].get("on_error") or {}).get(k) != (sb[sid].get("on_error") or {}).get(k):
                out.append(
                    {
                        "step_id": sid,
                        "kind": "changed",
                        "field": f"on_error.{k}",
                        "before": (sa[sid].get("on_error") or {}).get(k),
                        "after": (sb[sid].get("on_error") or {}).get(k),
                    }
                )
    return sorted(out, key=lambda c: int("".join(ch for ch in c["step_id"] if ch.isdigit()) or 0))


# ------------------------------------------------------------------------------------ KPIs & autonomy
SAVE_FACTOR = {
    "posted": 1.0,
    "rejected": 0.9,
    "reminder_sent": 1.0,
    "no_action": 0.3,
    "needs_review": 0.5,
    "rejected_by_approver": 0.3,
    "failed": 0.0,
    "simulated": 0.0,
    "done": 0.0,
}


def _save_factor(decision: str | None) -> float:
    if decision is None:
        return 0.0
    return SAVE_FACTOR.get(decision, 1.0)  # any completed sector route (refund, recommend, …) = fully handled


def kpis(emp: dict, settings: dict) -> dict:
    tasks = [t for t in db.query("tasks", employee_id=emp["id"], limit=2000) if t.get("mode") != "shadow"]
    minutes = {
        "collections": settings["minutes_per_collection_manual"],
        "ap": settings["minutes_per_invoice_manual"],
    }.get(emp["role"], settings.get("minutes_per_case_manual", 20))
    done = [t for t in tasks if t["status"] in ("done", "rejected")]
    finished = [t for t in tasks if t["status"] in ("done", "rejected", "needs_review", "failed")]
    hours = 0.0
    for t in tasks:
        dec = (t.get("outcome") or {}).get("final_decision")
        hours += _save_factor(dec) * minutes / 60
    calls = sum(int(t.get("ai_calls") or 0) for t in finished)
    durations = [t["duration_s"] for t in finished if t.get("duration_s")]
    bt = latest_backtest(emp["id"])
    reviewed = [
        t for t in tasks if (t.get("outcome") or {}).get("route") == "human_review" or t["status"] == "needs_review"
    ]
    return {
        "tasks_total": len(tasks),
        "tasks_done": len(done),
        "tasks_waiting_approval": sum(t["status"] == "waiting_approval" for t in tasks),
        "tasks_in_review": sum(t["status"] == "needs_review" for t in tasks),
        "tasks_failed": sum(t["status"] == "failed" for t in tasks),
        "accuracy": bt.get("route_accuracy") if bt else None,
        "hours_saved": round(hours, 1),
        "money_saved_inr": round(hours * settings["hourly_cost_inr"]),
        "ai_calls_total": calls,
        "ai_calls_per_task": round(calls / len(finished), 2) if finished else 0.0,
        "escalation_rate": round(len(reviewed) / len(finished), 2) if finished else 0.0,
        "avg_seconds_per_task": round(sum(durations) / len(durations), 1) if durations else 0.0,
    }


def latest_backtest(emp_id: str) -> dict | None:
    bts = [b for b in db.query("backtests", employee_id=emp_id, limit=20) if b.get("status") == "done"]
    return bts[0] if bts else None


def promotion(emp: dict) -> dict:
    """Earned autonomy: evidence from backtests (where the template has labelled history) and approvals."""
    lvl = int(emp.get("autonomy_level", 0))
    if lvl >= 2:
        return {
            "eligible": False,
            "next_level": None,
            "reason": "Already autonomous within SOP limits.",
            "accuracy": None,
            "sample_size": 0,
            "threshold": 0,
        }
    nxt = lvl + 1
    bt = latest_backtest(emp["id"])
    acc = bt.get("route_accuracy") if bt else None
    n = bt.get("n_tasks", 0) if bt else 0
    if (packs.get(emp["role"]) or {}).get("evaluation", {}).get("type", "shadow") == "shadow":
        if nxt == 1:
            ok = bt is not None
            return {
                "eligible": ok,
                "next_level": 1,
                "accuracy": acc,
                "sample_size": n,
                "threshold": 0,
                "reason": "Shadow run reviewed — ready to act with approval."
                if ok
                else "Run a shadow backtest on the ledger first.",
            }
        have = int(emp.get("supervised_approvals", 0))
        ok = have >= 3
        return {
            "eligible": ok,
            "next_level": 2,
            "accuracy": acc,
            "sample_size": have,
            "threshold": 3,
            "reason": f"{have}/3 supervised actions approved by a manager.",
        }
    # The evidence bar is per process: a template may lower/raise how many labelled cases a backtest needs.
    evaluation = (packs.get(emp["role"]) or {}).get("evaluation") or {}
    rule = {**config.PROMOTION[nxt]}
    if evaluation.get("min_tasks"):
        rule["min_backtest_tasks"] = int(evaluation["min_tasks"])
    reasons, ok = [], True
    if acc is None:
        ok = False
        reasons.append("no backtest yet — replay the labelled history first")
    else:
        if n < rule["min_backtest_tasks"]:
            ok = False
            reasons.append(f"backtest has {n} tasks (needs {rule['min_backtest_tasks']})")
        if acc < rule["min_backtest_accuracy"]:
            ok = False
            reasons.append(f"backtest accuracy {acc:.0%} is below {rule['min_backtest_accuracy']:.0%}")
        else:
            reasons.append(f"backtest accuracy {acc:.0%} ≥ {rule['min_backtest_accuracy']:.0%} on {n} past cases")
    if nxt == 2:
        have = int(emp.get("supervised_approvals", 0))
        need = rule["min_supervised_approvals"]
        if have < need:
            ok = False
        reasons.append(f"{have}/{need} supervised actions approved by a manager")
    return {
        "eligible": ok,
        "next_level": nxt,
        "reason": "; ".join(reasons),
        "accuracy": acc,
        "sample_size": n,
        "threshold": rule["min_backtest_accuracy"],
    }


def view(emp: dict, settings: dict) -> dict:
    out = {k: v for k, v in emp.items() if k != "status"}
    out.update({k: v for k, v in role_meta(emp["role"]).items() if k not in out})
    out["role"] = emp.get("role_title", emp["role"])
    out["role_key"] = emp["role"]
    out["autonomy_label"] = LEVELS[int(emp.get("autonomy_level", 0))]
    out["kpis"] = kpis(emp, settings)
    out["promotion"] = promotion(emp)
    return out
