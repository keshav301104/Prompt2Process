"""Hiring: SOP (+ optional template) -> clarifying questions -> workflow plan -> checker -> automatic repair.

Gemma 4 reads the SOP, asks about ambiguities, and writes the plan as JSON using ONLY the tools this role may
use. The checker verifies it and its errors are fed back for up to 2 repair rounds. If the model is unavailable
or cannot produce a valid plan, the chosen template's reference plan is used (clearly labelled), so hiring from a
template always works. Answers about people (who approves what) are saved to the organisation directory.
"""

import json

from .. import db, org
from ..core import checker
from ..core.registry import catalog
from ..llm.gemma import LLMUnavailable, llm
from ..safety import injection
from . import employees, packs

MAX_REPAIRS = 2
CUSTOM_ROLE = "custom"

PLAN_RULES = """Plan JSON format:
{"name": str, "description": str, "steps": [ {"id": "s1", "title": str, "action": <tool name>, "params": {..},
  "when": <condition or null>, "on_error": {"retry": 0-5, "fallback": null | "escalate_to_human" | "skip"},
  "requires_approval": bool } ]}
Rules:
- Use ONLY tools from the catalog, with ONLY their listed input names. Step ids s1, s2, ... in order; steps run top to bottom.
- Reference earlier outputs as "$s2.total" (one output field) or "$s1" (whole output). Task inputs: "$task.file" (a document),
  "$task.customer_id" (a ledger record) or "$task.folder" / "$task.case_id" (a case folder of documents).
  Organisation data: "$org.state_code", approvers from the directory: "$org.people.<key>". Inside text use "${s2.invoice_no}".
- Conditions ("when") are Python-like boolean expressions over earlier outputs, e.g. "s10.route == 'approval'",
  "s3.level > 0 and s2.label == 'high'". Only names of earlier steps, comparisons, and/or/not, in, len().
- Numbers in params are plain numbers (10000, not "₹10,000").
- Any step that moves money MUST have a "when" condition and MUST come after a request_approval step
  (requires_approval: true) guarded for the amounts that need approval.
- Hand anything uncertain to a person with escalate_to_human. Put SOP numbers (limits, tolerances, day counts) into params."""


def _directory_questions(pack: dict | None) -> list[dict]:
    have = {p["key"]: p for p in org.get()["people"]}
    out = []
    for d in (pack or {}).get("directory", []):
        cur = have.get(d["key"])
        out.append(
            {
                "id": f"dir:{d['key']}",
                "question": f"Who is the {d['role']}? (name and email)",
                "why": f"The SOP routes approvals or escalations to the {d['role']}; they will be saved in your "
                "people directory, never hardcoded in the workflow.",
                "suggested": f"{cur['name']} ({cur['email']})"
                if cur and cur.get("email")
                else (cur or {}).get("name", ""),
                "directory": {"key": d["key"], "role": d["role"]},
            }
        )
    return out


def draft(name: str, template_id: str | None, sop_text: str | None, use_ai: bool = True) -> dict:
    pack = packs.get(template_id) or (packs.get(packs.detect(sop_text)) if sop_text else None)
    sop = sop_text or (pack or {}).get("sop", "")
    if not sop.strip():
        raise ValueError("choose a template or provide an SOP")
    role = pack["id"] if pack else CUSTOM_ROLE
    questions = _directory_questions(pack)
    summary, method = "", "template"
    try:
        if not use_ai:
            raise LLMUnavailable("template questions requested")
        o = org.get()
        ans = llm.generate_json(
            "You are onboarding a new digital employee from a company SOP. List the 1-3 most important AMBIGUITIES "
            "(vague rules or missing numbers) an automated employee could not resolve on its own — do NOT ask who "
            "people are (that is handled separately). For each: a short question, why it matters, a sensible "
            f"suggested answer.\nOrganisation: {o['name'] or 'unnamed'} ({o['industry'] or 'industry not set'}).\n"
            'Return JSON: {"summary": "<2 sentence summary of the role>", "questions": [{"question": "...", '
            '"why": "...", "suggested": "..."}]}\n' + injection.wrap_document(sop[:12000]),
            purpose="hire:clarify",
        )
        questions += [
            {
                "id": f"q{i + 1}",
                "question": q.get("question", ""),
                "why": q.get("why", ""),
                "suggested": q.get("suggested", ""),
            }
            for i, q in enumerate(ans.get("questions", [])[:3])
        ]
        summary, method = ans.get("summary", ""), "gemma"
    except (LLMUnavailable, ValueError):
        questions += [dict(q) for q in (pack or {}).get("questions", [])]
        summary = " ".join(ln.strip() for ln in sop.splitlines() if ln.strip() and not ln.startswith(("#", "**")))[:300]
    d = {
        "id": db.new_id("draft"),
        "name": name.strip() or (pack or {}).get("employee", {}).get("name", "New employee"),
        "role": role,
        "template_id": (pack or {}).get("id"),
        "sop_text": sop,
        "questions": questions,
        "summary": summary,
        "method": method,
        "status": "draft",
    }
    db.put("drafts", d)
    return {
        "draft_id": d["id"],
        "sop_summary": summary,
        "detected_role": role,
        "template_id": d["template_id"],
        "questions": questions,
        "method": method,
    }


def _catalog_text(role: str) -> str:
    return json.dumps(
        [{k: t[k] for k in ("name", "description", "inputs", "outputs")} for t in catalog(role)], ensure_ascii=False
    )


def compile_plan(draft_id: str, answers: dict, reference_only: bool = False) -> dict:
    d = db.get("drafts", draft_id)
    if not d:
        raise ValueError("draft not found")
    for q in d["questions"]:  # people answers -> organisation directory
        if q.get("directory") and (answers.get(q["id"]) or q.get("suggested")):
            org.set_person(q["directory"]["key"], q["directory"]["role"], answers.get(q["id"]) or q["suggested"])
    role, sop, pack = d["role"], d["sop_text"], packs.get(d.get("template_id"))
    who = pack["employee"]["title"] if pack else "back-office employee"
    unit = {
        "folder": "one document ($task.file)",
        "ledger": "one ledger record ($task.customer_id)",
        "cases": "one case — a folder of documents ($task.folder, $task.case_id)",
    }.get(((pack or {}).get("intake") or {}).get("type", "cases"), "one case")
    qa = "\n".join(f"Q: {q['question']}\nA: {answers.get(q['id']) or q.get('suggested', '')}" for q in d["questions"])
    attempts, plan, report = [], None, None
    try:
        if reference_only:
            raise LLMUnavailable("reference plan requested")
        raw = llm.generate_json(
            f"You are a compiler that turns a company SOP into an executable workflow plan for a digital {who}. "
            f"One plan handles ONE task ({unit}).\n\n{PLAN_RULES}\n\nTool catalog (JSON):\n{_catalog_text(role)}\n\n"
            f"Manager's answers to clarifying questions:\n{qa}\n\nSOP:\n"
            + injection.wrap_document(sop[:12000])
            + "\n\nWrite the complete plan JSON.",
            purpose="hire:compile",
            max_tokens=8000,
        )
        for attempt in range(1, MAX_REPAIRS + 2):
            report, normalised = checker.check(raw, role)
            attempts.append({"attempt": attempt, "ok": report["ok"], "errors": report["errors"][:12], "by": "gemma"})
            if report["ok"]:
                plan = normalised
                break
            if attempt > MAX_REPAIRS:
                break
            raw = llm.generate_json(
                f"{PLAN_RULES}\n\nTool catalog (JSON):\n{_catalog_text(role)}\n\nThis plan failed the checker:\n"
                f"{json.dumps(raw, ensure_ascii=False)}\n\nChecker errors:\n- "
                + "\n- ".join(report["errors"])
                + "\n\nFix every error and return the full corrected plan JSON.",
                purpose="hire:repair",
                max_tokens=8000,
            )
    except (LLMUnavailable, ValueError) as e:
        if not reference_only:
            attempts.append(
                {"attempt": len(attempts) + 1, "ok": False, "errors": [f"model unavailable: {e}"], "by": "gemma"}
            )

    if plan is None and pack:  # the template's reference plan, still checked
        report, plan = checker.check(packs.plan_for(pack), role)
        attempts.append(
            {
                "attempt": len(attempts) + 1,
                "ok": report["ok"],
                "errors": report["errors"],
                "by": f"template '{pack['id']}' (reference plan)",
            }
        )
    if plan is None:
        raise ValueError("Gemma could not compile a valid plan for this custom SOP — check the model connection.")
    d.update(plan=plan, check=report, attempts=attempts, status="compiled", answers=answers)
    db.put("drafts", d)
    return {
        "draft_id": draft_id,
        "plan": plan,
        "check": report,
        "attempts": attempts,
        "tools": employees.tools_for(role),
    }


def confirm(draft_id: str, name: str | None = None) -> dict:
    d = db.get("drafts", draft_id)
    if not d or not d.get("plan"):
        raise ValueError("draft has no compiled plan")
    if not (d.get("check") or {}).get("ok"):
        raise ValueError("plan does not pass the checker")
    pack = packs.get(d.get("template_id"))
    title = (
        packs.sop_title(pack)
        if pack and d["sop_text"] == pack["sop"]
        else next((ln.lstrip("# ").strip() for ln in d["sop_text"].splitlines() if ln.strip()), "Custom SOP")
    )
    emp = employees.create(name or d["name"], d["role"], d["plan"], sop_title=title[:80])
    db.update("drafts", draft_id, status="hired", employee_id=emp["id"])
    return emp


def hire_from_template(template_id: str, name: str, answers: dict | None = None, reference_only: bool = False) -> dict:
    """The whole pipeline in one call (used by 'Load demo workspace' and the API)."""
    d = draft(name, template_id, None, use_ai=not reference_only)  # the demo uses the templates' own questions
    compile_plan(d["draft_id"], answers or {}, reference_only=reference_only)
    return confirm(d["draft_id"])
