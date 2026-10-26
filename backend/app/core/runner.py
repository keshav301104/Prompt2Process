"""Executes a checked plan for one task on LangGraph.

The plan is interpreted by a one-node LangGraph state machine (program counter + outputs). LangGraph gives us:
  * checkpoints after every step (SQLite) -> a crashed or paused task resumes exactly where it stopped
  * interrupt() -> human approval gates, resumed with Command(resume=decision)
Autonomy: Shadow (level 0) simulates every side effect; Supervised (1) asks before each side effect;
Autonomous (2) only stops where the SOP requires approval.
"""

import json
import random
import sqlite3
import time
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .. import company as co
from .. import db
from ..config import STATE_DIR
from ..llm.gemma import CALL_COUNTER
from . import expr
from .registry import REGISTRY, ExecContext, PolicyError, TransientError

_ckpt_conn = sqlite3.connect(STATE_DIR / "checkpoints.sqlite", check_same_thread=False)
SQLITE_SAVER = SqliteSaver(_ckpt_conn)
MEMORY_SAVER = InMemorySaver()


class TaskState(TypedDict, total=False):
    pc: int
    outputs: dict
    flags: list
    halted: str | None
    ai_calls: int
    signed_off: bool  # Supervised mode: a manager signed off this task's actions


def preview(out: dict) -> str:
    keep = {k: v for k, v in out.items() if k not in ("text", "line_items", "lines", "body") and not k.startswith("_")}
    s = json.dumps(keep, default=str, ensure_ascii=False)
    return s if len(s) <= 300 else s[:297] + "..."


# ------------------------------------------------------------------------------------------- recorders
class MemoryRecorder:
    """Keeps the task in memory (used by backtests / shadow runs)."""

    def __init__(self, task: dict):
        self.task = task
        self.task.setdefault("steps", [])
        self.task.setdefault("fields", {})
        self.task.setdefault("flags", [])
        self.events: list = []

    def _step(self, step_id):
        return next((s for s in self.task["steps"] if s["step_id"] == step_id), None)

    def step(self, step: dict, status: str, **extra) -> None:
        s = self._step(step["id"])
        if s is None:
            s = {
                "step_id": step["id"],
                "title": step.get("title") or step["action"],
                "action": step["action"],
                "status": "pending",
                "attempts": 0,
                "ai_calls": 0,
            }
            self.task["steps"].append(s)
        if status == "running" and not s.get("started_at"):
            s["started_at"] = db.now()
        if status in ("ok", "failed", "skipped", "simulated", "fallback"):
            s["ended_at"] = db.now()
        s["status"] = status
        s.update({k: v for k, v in extra.items() if v is not None})

    def fields(self, fields: dict) -> None:
        self.task["fields"].update(fields)

    def flags(self, flags: list) -> None:
        self.task["flags"].extend(flags)

    def event(self, level: str, message: str, step_id: str | None = None) -> None:
        self.events.append({"ts": db.now(), "level": level, "message": message, "step_id": step_id})

    def status(self, status: str) -> None:
        self.task["status"] = status

    def save(self) -> None:
        pass


class DBRecorder(MemoryRecorder):
    """Same as MemoryRecorder but persists every change so the console sees it live."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(db.must("tasks", task_id))

    def save(self) -> None:
        live = db.get("tasks", self.task_id) or {}
        # never overwrite a decision a human made in the meantime
        for k in ("steps", "fields", "flags", "status", "ai_calls", "outcome", "ref", "title", "duration_s"):
            if k in self.task:
                live[k] = self.task[k]
        db.put("tasks", live)

    def step(self, step, status, **extra):
        super().step(step, status, **extra)
        self.save()

    def fields(self, fields):
        super().fields(fields)
        self.save()

    def flags(self, flags):
        super().flags(flags)
        self.save()

    def event(self, level, message, step_id=None):
        db.event(self.task_id, level, message, step_id)

    def status(self, status):
        super().status(status)
        self.save()


# ------------------------------------------------------------------------------------------- runner
class Runner:
    def __init__(
        self,
        plan: dict,
        employee: dict,
        task: dict,
        settings: dict,
        mode: str = "live",
        recorder: MemoryRecorder | None = None,
        seen: list | None = None,
    ):
        self.plan = plan
        self.steps = plan["steps"]
        self.employee = employee
        self.task = task
        self.settings = settings
        self.mode = mode
        self.level = 0 if mode == "shadow" else int(employee.get("autonomy_level", 0))
        self.rec = recorder or MemoryRecorder(task)
        self.seen = seen
        self.thread_id = task.get("thread_id") or task["id"]
        saver = SQLITE_SAVER if mode == "live" else MEMORY_SAVER
        g = StateGraph(TaskState)
        g.add_node("step", self._step)
        g.add_edge(START, "step")
        g.add_conditional_edges("step", self._next, {"step": "step", END: END})
        self.graph = g.compile(checkpointer=saver)
        self.config = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": 4 * len(self.steps) + 20}

    # -------------------------------------------------------------- public
    def start(self) -> str:
        self.rec.status("running")
        for s in self.steps:
            if not self.rec._step(s["id"]):
                self.rec.step(s, "pending")
        self.rec.event("info", f"{self.employee.get('name')} started ({self._level_label()})")
        self.graph.invoke({"pc": 0, "outputs": {}, "flags": [], "halted": None, "ai_calls": 0}, self.config)
        return self._after()

    def resume(self, decision: dict) -> str:
        self.rec.status("running")
        self.graph.invoke(Command(resume=decision), self.config)
        return self._after()

    def state(self) -> dict:
        return self.graph.get_state(self.config).values

    # -------------------------------------------------------------- graph pieces
    def _next(self, state: TaskState):
        if state.get("halted") or state.get("pc", 0) >= len(self.steps):
            return END
        return "step"

    def _level_label(self) -> str:
        return "shadow mode" if self.mode == "shadow" else ["Shadow", "Supervised", "Autonomous"][self.level]

    def _scope(self, state: TaskState) -> dict:
        scope = dict(state.get("outputs") or {})
        scope["task"] = {
            k: self.task.get(k) for k in ("id", "file", "title", "customer_id", "case_id", "folder", "files")
        }
        scope["company"] = co.company()
        scope["org"] = co.company()
        scope["employee"] = {"name": self.employee.get("name"), "id": self.employee.get("id")}
        return scope

    def _step(self, state: TaskState) -> dict:
        pc = state.get("pc", 0)
        step = self.steps[pc]
        spec = REGISTRY[step["action"]]
        scope = self._scope(state)
        title = step.get("title") or step["action"]

        if step.get("when"):
            try:
                go = expr.evaluate(step["when"], scope)
            except expr.ExprError as e:
                go = False
                self.rec.event("warn", f"{title}: condition error ({e}) — skipped", step["id"])
            if not go:
                self.rec.step(step, "skipped", output_preview=f"condition false: {step['when']}")
                return {"pc": pc + 1}

        params = expr.resolve_value(step.get("params") or {}, scope)
        shadow = self.mode == "shadow" or self.level == 0

        # ---- Shadow: never touch the outside world, never bother a human
        if shadow and (spec.side_effect or step.get("requires_approval") or spec.halts):
            what = {
                "escalate_to_human": "hand to a human for review",
                "request_approval": f"ask {', '.join(params.get('approvers') or []) or 'approver'} for approval",
            }
            msg = f"Would {what.get(spec.name, 'run ' + spec.name)}"
            self.rec.step(step, "simulated", output_preview=msg)
            self.rec.event("info", f"[shadow] {title}: {msg}", step["id"])
            outs = dict(state.get("outputs") or {})
            outs[step["id"]] = {"simulated": True, **({"approved": True} if spec.name == "request_approval" else {})}
            upd = {"pc": pc + 1, "outputs": outs}
            if spec.halts:
                upd["halted"] = "needs_review"
            return upd

        # ---- Approval gate: SOP approvals always; while Supervised, one sign-off covers the task's actions
        supervised_gate = spec.side_effect and self.level == 1 and not state.get("signed_off")
        signed_now = False
        if step.get("requires_approval") or supervised_gate:
            pending = self._pending_actions(pc, scope) if supervised_gate and not step.get("requires_approval") else []
            inbox_id = self._approval_item(step, params, spec, pending)
            self.rec.step(step, "waiting_approval")
            self.rec.status("waiting_approval")
            decision = interrupt({"inbox_id": inbox_id, "step_id": step["id"]})
            if (decision or {}).get("decision") != "approve":
                self.rec.step(
                    step,
                    "failed",
                    error=f"Rejected by {decision.get('by', 'approver')}: {decision.get('note') or ''}".strip(),
                )
                self.rec.event("warn", f"{title}: rejected by approver", step["id"])
                return {"pc": len(self.steps), "halted": "rejected"}
            self.rec.event("success", f"{title}: approved by {decision.get('by', 'approver')}", step["id"])
            self.rec.status("running")
            signed_now = self.level == 1

        # ---- Execute with retries
        ctx = ExecContext(
            task=self.task,
            employee=self.employee,
            settings=self.settings,
            mode=self.mode,
            step_id=step["id"],
            flags=list(state.get("flags") or []),
            outputs=state.get("outputs") or {},
            seen=self.seen,
        )
        retries = int((step.get("on_error") or {}).get("retry", 1))
        chaos = self.settings.get("chaos_mode") and not spec.side_effect and not spec.halts
        out: dict | None = None
        err: Exception | None = None
        attempts = 0
        counter = {"n": 0}
        token = CALL_COUNTER.set(counter)
        try:
            for attempt in range(retries + 1):
                attempts = attempt + 1
                self.rec.step(step, "running" if attempt == 0 else "retrying", attempts=attempts)
                try:
                    if chaos and random.random() < float(self.settings.get("chaos_rate", 0.25)):
                        raise TransientError("injected failure (chaos mode): upstream service timed out")
                    out = spec.fn(ctx, **params)
                    break
                except PolicyError as e:
                    err = e
                    self.rec.event("error", f"{title}: blocked by policy — {e}", step["id"])
                    break
                except Exception as e:
                    err = e
                    self.rec.event("warn", f"{title}: attempt {attempts} failed — {e}", step["id"])
                    time.sleep(0.4 if chaos else 0.1)
        finally:
            CALL_COUNTER.reset(token)

        if out is None:
            return self._on_failure(step, spec, state, err, attempts, counter["n"])

        new_flags = out.pop("_flags", []) or []
        fields = out.pop("_fields", {}) or {}
        if fields:
            if spec.name == "extract_invoice" and out.get("vendor_name"):
                self.rec.task["title"] = f"{out.get('vendor_name')} · {out.get('invoice_no') or ''}".strip(" ·")
            if spec.name == "load_customer" and out.get("name"):
                self.rec.task["title"] = f"{out.get('name')} · {out.get('invoice_no') or ''}".strip(" ·")
            self.rec.fields(fields)
        if new_flags:
            self.rec.flags(new_flags)
            for f in new_flags:
                self.rec.event(
                    "warn" if f["severity"] != "critical" else "error", f"⚑ {f['type']}: {f['message']}", step["id"]
                )
        outs = dict(state.get("outputs") or {})
        outs[step["id"]] = out
        self.rec.step(step, "ok", attempts=attempts, ai_calls=counter["n"], output_preview=preview(out), error=None)
        if attempts > 1:
            self.rec.event(
                "success", f"{title}: recovered after {attempts - 1} retr{'y' if attempts == 2 else 'ies'}", step["id"]
            )
        upd = {
            "pc": pc + 1,
            "outputs": outs,
            "flags": list(state.get("flags") or []) + new_flags,
            "ai_calls": int(state.get("ai_calls") or 0) + counter["n"],
        }
        if signed_now:
            upd["signed_off"] = True
        if spec.halts:
            upd["halted"] = "needs_review"
            self.rec.event("info", f"{title}: handed to a human — {params.get('reason', '')}"[:300], step["id"])
        return upd

    def _on_failure(self, step, spec, state, err, attempts, calls) -> dict:
        title = step.get("title") or step["action"]
        fb = (step.get("on_error") or {}).get("fallback")
        if fb == "skip":
            self.rec.step(step, "fallback", attempts=attempts, error=f"{err} — skipped (fallback)")
            outs = dict(state.get("outputs") or {})
            outs[step["id"]] = {"failed": True, "error": str(err)}
            return {"pc": step_index(self.steps, step["id"]) + 1, "outputs": outs}
        if fb == "escalate_to_human":
            self.rec.step(step, "fallback", attempts=attempts, error=f"{err} — handed to a human (fallback)")
            if self.mode != "shadow" and self.level > 0:
                ctx = ExecContext(
                    task=self.task,
                    employee=self.employee,
                    settings=self.settings,
                    mode=self.mode,
                    step_id=step["id"],
                    flags=list(state.get("flags") or []),
                )
                REGISTRY["escalate_to_human"].fn(ctx, reason=f"Step '{title}' failed after {attempts} attempts: {err}")
            return {"pc": len(self.steps), "halted": "needs_review"}
        self.rec.step(step, "failed", attempts=attempts, error=str(err), ai_calls=calls)
        self.rec.event("error", f"{title}: failed after {attempts} attempt(s) — {err}", step["id"])
        if self.mode != "shadow":
            from ..workforce import healing

            healing.propose(self.employee, self.task, step, str(err))
        return {"pc": len(self.steps), "halted": "failed"}

    def _pending_actions(self, pc: int, scope: dict) -> list[str]:
        """Titles of the side-effecting steps this task is about to take (what a Supervised sign-off covers)."""
        out = []
        for s in self.steps[pc:]:
            if not REGISTRY[s["action"]].side_effect:
                continue
            try:
                if s.get("when") and not expr.evaluate(s["when"], scope):
                    continue
            except expr.ExprError:
                pass  # depends on a later step's output — list it to be safe
            out.append(s.get("title") or s["action"])
        return out

    def _approval_item(self, step: dict, params: dict, spec, pending: list[str] | None = None) -> str:
        # On resume LangGraph re-enters this step: reuse this run's item (open or already decided), never duplicate.
        existing = [
            i
            for i in db.query("inbox", employee_id=self.employee["id"], limit=2000)
            if i.get("task_id") == self.task["id"]
            and i.get("payload", {}).get("step_id") == step["id"]
            and i.get("payload", {}).get("thread_id", self.thread_id) == self.thread_id
        ]
        if existing:
            return existing[0]["id"]
        f = self.rec.task.get("fields") or {}
        amount = params.get("amount") or (f.get("total") or {}).get("value") or (f.get("amount") or {}).get("value")
        approvers = [a for a in (params.get("approvers") or []) if a] or (
            ["approver not set in the directory"] if params.get("approvers") else ["Manager (supervised mode)"]
        )
        if pending:
            reason = f"Supervised mode: approve {self.employee.get('name')}'s actions on this case — " + "; ".join(
                pending
            )
        else:
            reason = params.get("reason") or (
                f"Supervised mode: {self.employee.get('name')} needs sign-off before '{step.get('title') or spec.name}'"
            )
        item = {
            "id": db.new_id("inb"),
            "task_id": self.task["id"],
            "employee_id": self.employee["id"],
            "kind": "approval",
            "status": "open",
            "title": f"{step.get('title') or spec.name} — {self.task.get('title', '')}",
            "reason": reason if isinstance(reason, str) else "; ".join(reason),
            "payload": {
                "step_id": step["id"],
                "thread_id": self.thread_id,
                "step_title": step.get("title") or spec.name,
                "action": spec.name,
                "amount": amount,
                "vendor": (f.get("vendor_name") or f.get("customer") or {}).get("value"),
                "approvers": approvers if isinstance(approvers, list) else [str(approvers)],
                "reason": reason,
                "params_preview": preview(params),
                "supervised": self.level == 1,
                "covers": pending or [step.get("title") or spec.name],
            },
        }
        db.put("inbox", item)
        self.rec.event("info", f"Waiting for approval: {item['title']}", step["id"])
        return item["id"]

    def _after(self) -> str:
        snap = self.graph.get_state(self.config)
        st = snap.values or {}
        if snap.next:  # paused at an interrupt
            self.rec.status("waiting_approval")
            self.rec.save()
            return "waiting_approval"
        outs = st.get("outputs") or {}
        halted = st.get("halted")
        outcome = summarise_outcome(self.steps, outs, halted, self.mode)
        self.rec.task["outcome"] = outcome
        self.rec.task["ai_calls"] = int(st.get("ai_calls") or 0)
        self.rec.task["ref"] = reference(self.steps, outs)
        inv = self.rec.task["ref"].get("invoice") or {}
        if inv.get("vendor_name"):
            self.rec.task["title"] = f"{inv.get('vendor_name')} · {inv.get('invoice_no') or ''}".strip(" ·")
        status = {"needs_review": "needs_review", "rejected": "rejected", "failed": "failed"}.get(halted or "", "done")
        if self.mode == "shadow":
            status = "done"
        self.rec.status(status)
        self.rec.event("success" if status == "done" else "warn", f"Finished: {outcome.get('summary', status)}")
        return status


def step_index(steps: list, step_id: str) -> int:
    return next(i for i, s in enumerate(steps) if s["id"] == step_id)


def _by_action(steps: list, outs: dict, action: str) -> dict | None:
    for s in steps:
        if s["action"] == action and s["id"] in outs:
            return outs[s["id"]]
    return None


def reference(steps: list, outs: dict) -> dict:
    """What a human (or later step) needs to finish the task: the invoice/customer data and key decisions."""
    ref: dict[str, Any] = {}
    inv = _by_action(steps, outs, "extract_invoice")
    if inv:
        ref["invoice"] = {k: v for k, v in inv.items() if k != "text"}
    v = _by_action(steps, outs, "match_vendor")
    if v:
        ref["vendor_id"] = v.get("vendor_id")
        ref["vendor_known"] = v.get("known")
    c = _by_action(steps, outs, "classify_expense")
    if c and not c.get("failed"):
        ref["category"] = c.get("category")
        ref["category_text"] = c.get("text")
    r = _by_action(steps, outs, "decide_route")
    if r:
        ref["route"] = r.get("route")
        ref["approvers"] = r.get("approvers")
    cust = _by_action(steps, outs, "load_customer")
    if cust:
        ref["customer"] = cust
    d = _by_action(steps, outs, "draft_reminder")
    if d and not d.get("simulated"):
        ref["draft"] = {"subject": d.get("subject"), "body": d.get("body"), "language": d.get("language")}
    lvl = _by_action(steps, outs, "choose_reminder_level")
    if lvl:
        ref["level"] = lvl.get("level")
    rk = _by_action(steps, outs, "score_payment_risk")
    if rk:
        ref["risk"] = rk.get("label")
    case = _by_action(steps, outs, "extract_case")
    if case:
        ref["case_fields"] = case.get("fields")
    intake = _by_action(steps, outs, "intake_case")
    if intake:
        ref["files"] = intake.get("files")
        ref["missing"] = intake.get("missing")
    dec = _by_action(steps, outs, "decide")
    if dec:
        ref["route"] = dec.get("route")
        ref["reason"] = dec.get("reason")
    for s in steps:
        o = outs.get(s["id"]) or {}
        if s["action"] == "draft_message" and o.get("body") and not o.get("simulated"):
            ref["draft"] = {"subject": o.get("subject"), "body": o.get("body"), "language": o.get("language")}
    return ref


def summarise_outcome(steps: list, outs: dict, halted: str | None, mode: str) -> dict:
    ran = {
        s["action"]
        for s in steps
        if s["id"] in outs and not outs[s["id"]].get("simulated") and not outs[s["id"]].get("failed")
    }
    dec = _by_action(steps, outs, "decide")
    if dec is not None or _by_action(steps, outs, "intake_case") is not None:
        route = (dec or {}).get("route") or "human_review"
        if halted == "rejected":
            return {
                "route": route,
                "final_decision": "rejected_by_approver",
                "summary": "Approver rejected — nothing executed",
            }
        if halted == "failed":
            return {
                "route": route,
                "final_decision": "failed",
                "summary": "Failed — self-healing proposal sent to inbox",
            }
        if halted == "needs_review" or route == "human_review":
            return {
                "route": "human_review",
                "final_decision": "needs_review",
                "summary": ((dec or {}).get("reason") or "Handed to a human for review"),
            }
        return {
            "route": route,
            "final_decision": route if mode != "shadow" else "simulated",
            "summary": (dec or {}).get("reason") or route,
        }
    route = (_by_action(steps, outs, "decide_route") or {}).get("route")
    lvl = _by_action(steps, outs, "choose_reminder_level")
    if halted == "rejected":
        return {
            "route": route,
            "final_decision": "rejected_by_approver",
            "summary": "Approver rejected — nothing booked",
        }
    if halted == "failed":
        return {"route": route, "final_decision": "failed", "summary": "Failed — self-healing proposal sent to inbox"}
    if halted == "needs_review":
        return {
            "route": route or "human_review",
            "final_decision": "needs_review",
            "summary": "Handed to a human for review" if mode != "shadow" else "Would hand to a human",
        }
    if lvl is not None:
        if not lvl.get("level"):
            return {
                "route": "no_action",
                "final_decision": "no_action",
                "summary": "Not overdue enough for a reminder yet",
            }
        sent = "send_reminder" in ran
        return {
            "route": f"level_{lvl['level']}",
            "final_decision": "reminder_sent" if sent else "simulated",
            "summary": f"Level {lvl['level']} reminder {'sent' if sent else 'drafted (shadow)'}",
        }
    if "post_journal_entry" in ran:
        return {"route": route, "final_decision": "posted", "summary": f"Posted and scheduled for payment ({route})"}
    if "reject_invoice" in ran:
        return {"route": route, "final_decision": "rejected", "summary": "Rejected and vendor notified"}
    return {
        "route": route,
        "final_decision": "simulated" if mode == "shadow" else "done",
        "summary": f"Route: {route}" + (" (shadow — nothing executed)" if mode == "shadow" else ""),
    }
