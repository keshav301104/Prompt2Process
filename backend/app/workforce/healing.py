"""Self-healing: when a step keeps failing, propose a bounded fix to the plan, verify it with the checker,
and ask a human to approve it. Gemma explains the failure; the patch itself is limited to safe fields."""

import contextlib
import copy

from .. import db
from ..core import checker
from ..llm.gemma import LLMUnavailable, llm


def _patch_for(step: dict, error: str) -> list[dict]:
    oe = step.get("on_error") or {}
    patch = []
    retry = int(oe.get("retry", 1))
    if retry < 4:
        patch.append({"step_id": step["id"], "field": "on_error.retry", "before": retry, "after": min(5, retry + 2)})
    if oe.get("fallback") != "escalate_to_human":
        patch.append(
            {
                "step_id": step["id"],
                "field": "on_error.fallback",
                "before": oe.get("fallback"),
                "after": "escalate_to_human",
            }
        )
    return patch


def apply(plan: dict, patch: list[dict]) -> dict:
    new = copy.deepcopy(plan)
    for p in patch:
        s = next(x for x in new["steps"] if x["id"] == p["step_id"])
        if p["field"].startswith("on_error."):
            s.setdefault("on_error", {})[p["field"].split(".", 1)[1]] = p["after"]
        elif p["field"].startswith("params."):
            s.setdefault("params", {})[p["field"].split(".", 1)[1]] = p["after"]
        else:
            s[p["field"]] = p["after"]
    return new


def propose(employee: dict, task: dict, step: dict, error: str) -> dict | None:
    emp = db.get("employees", employee["id"]) or employee
    for i in db.query("inbox", employee_id=emp["id"], status="open"):
        if i["kind"] == "healing" and i["payload"].get("step_id") == step["id"]:
            i["payload"].setdefault("task_ids", []).append(task["id"])
            db.put("inbox", i)
            return i
    patch = _patch_for(step, error)
    if not patch:
        return None
    new_plan = apply(emp["plan"], patch)
    report, _ = checker.check(new_plan, emp["role"], emp.get("tools"))
    explanation = (
        f"'{step.get('title')}' failed after all retries ({error}). Proposed fix: retry more times with "
        f"backoff and, if it still fails, hand the task to a human instead of stopping the queue."
    )
    with contextlib.suppress(LLMUnavailable):
        explanation = (
            llm.generate(
                "You are the reliability engineer of an automation platform. In 2-3 plain sentences for a finance manager, "
                f"explain this failure and why the proposed fix is safe.\nStep: {step.get('title')} ({step['action']})\n"
                f"Error: {error}\nProposed patch: {patch}",
                purpose="healing_explanation",
                max_tokens=300,
            ).strip()
            or explanation
        )
    item = {
        "id": db.new_id("inb"),
        "task_id": task["id"],
        "employee_id": emp["id"],
        "kind": "healing",
        "status": "open",
        "title": f"Self-healing proposal: {step.get('title')}",
        "reason": f"Step failed after retries: {error}",
        "payload": {
            "step_id": step["id"],
            "error": error,
            "patch": patch,
            "check": report,
            "explanation": explanation,
            "task_ids": [task["id"]],
        },
    }
    db.put("inbox", item)
    db.audit(emp.get("name", "employee"), "healing_proposed", f"{step['id']}: {error}", task["id"])
    return item
