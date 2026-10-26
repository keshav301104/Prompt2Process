"""The template library: every kind of digital employee is DATA (YAML in app/packs/), never code.

A template either
  * spells out its workflow plan directly (`plan:` with {{parameter}} placeholders) — e.g. Accounts Payable, or
  * describes a document case declaratively (documents, ids, cross-checks, formulas, rules, decision table,
    approvals, messages) and `plan_for()` compiles it into a plan made only of general skills — e.g. Banking.

Templates also declare their intake channel, how they are evaluated (backtests), which people they need in the
organisation's directory (approvers) and the clarifying questions to ask when hiring.
"""

import copy
import re
from functools import lru_cache
from pathlib import Path

import yaml

PACK_DIR = Path(__file__).resolve().parents[1] / "packs"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    packs = {}
    for f in sorted(PACK_DIR.glob("*.yaml")):
        p = yaml.safe_load(f.read_text(encoding="utf-8"))
        packs[p["id"]] = p
    return packs


def all_packs() -> list[dict]:
    return list(_load().values())


def get(pack_id: str | None) -> dict | None:
    return _load().get(pack_id or "")


def summary(p: dict) -> dict:
    return {
        "id": p["id"],
        "sector": p["sector"],
        "department": p["department"],
        "case_noun": p["case_noun"],
        "employee": p["employee"],
        "intake": p.get("intake"),
        "directory": p.get("directory", []),
        "parameters": p.get("parameters", {}),
        "documents": {k: v["title"] for k, v in (p.get("documents") or {}).items()},
        "routes": {k: v.get("label", k) for k, v in (p.get("routes") or {}).items()},
    }


def sop_title(p: dict) -> str:
    return next((ln.lstrip("# ").strip() for ln in p["sop"].splitlines() if ln.strip()), p["department"])


def detect(text: str) -> str | None:
    """Best-matching template for an uploaded SOP (keyword evidence), or None."""
    t = text.lower()
    best, score = None, 0
    for p in all_packs():
        s = sum(len(re.findall(rf"\b{re.escape(k)}\b", t)) for k in p.get("keywords", []))
        if s > score:
            best, score = p["id"], s
    return best if score >= 3 else None


# ------------------------------------------------------------------------------------ parameters
_WHOLE = re.compile(r"^\{\{(\w+)\}\}$")
_INLINE = re.compile(r"\{\{(\w+)\}\}")


def _fill(obj, params: dict):
    """Replace {{name}} placeholders: a whole-string placeholder keeps the value's type (number, list, dict)."""
    if isinstance(obj, str):
        m = _WHOLE.match(obj.strip())
        if m and m.group(1) in params:
            return copy.deepcopy(params[m.group(1)])
        return _INLINE.sub(lambda mm: str(params.get(mm.group(1), mm.group(0))), obj)
    if isinstance(obj, dict):
        return {k: _fill(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, params) for v in obj]
    return obj


def plan_for(p: dict, params: dict | None = None) -> dict:
    values = {**(p.get("parameters") or {}), **(params or {})}
    if p.get("plan"):
        return _fill(copy.deepcopy(p["plan"]), values)
    return _case_plan(p)


# ------------------------------------------------------------------------------------ declarative case plans
EXTRACT, INTAKE, METRICS, CLASSIFY, IMAGE, DECIDE = "s2", "s1", "s6", "s7", "s8", "s10"


def _qualify(expr_text: str, p: dict) -> str:
    """Pack-level names (application.loan_amount, payable) -> step references (s2.fields…, s6.values…)."""
    out = expr_text
    for d in p["documents"]:
        out = re.sub(rf"(?<![\w.]){d}\.", f"{EXTRACT}.fields.{d}.", out)
    for m in p.get("formulas") or {}:
        out = re.sub(rf"(?<![\w.]){m}\b", f"{METRICS}.values.{m}", out)
    return out


_PLACEHOLDER = re.compile(r"\{(fields|metrics|missing|reason)((?:\.\w+)*)\}")


def _text(template: str) -> str:
    """'Rs. {fields.application.loan_amount}' -> 'Rs. ${s2.fields.application.loan_amount}'."""
    roots = {
        "fields": f"{EXTRACT}.fields",
        "metrics": f"{METRICS}.values",
        "missing": f"{INTAKE}.missing",
        "reason": f"{DECIDE}.reason",
    }
    return _PLACEHOLDER.sub(lambda m: "${" + roots[m.group(1)] + m.group(2) + "}", template)


def _ref(path: str) -> str:
    return f"${EXTRACT}.fields.{path}"


def _s(id_, title, action, params, when=None, retry=1, fallback=None, approval=False):
    return {
        "id": id_,
        "title": title,
        "action": action,
        "params": params,
        "when": when,
        "on_error": {"retry": retry, "fallback": fallback},
        "requires_approval": approval,
    }


def _case_plan(p: dict) -> dict:
    docs = p["documents"]
    schema = {d: copy.deepcopy(spec["fields"]) for d, spec in docs.items()}
    required = [d for d, spec in docs.items() if spec.get("required")]
    contact = p.get("contact", {})
    metrics = f"${METRICS}.values" if p.get("formulas") else {}
    steps = [
        _s(
            INTAKE,
            f"Open the {p['case_noun']} & screen documents",
            "intake_case",
            {"folder": "$task.folder", "required_documents": required},
        ),
        _s(
            EXTRACT,
            "Read documents into the schema",
            "extract_case",
            {"documents": f"${INTAKE}.documents", "schema": schema},
            retry=2,
            fallback="escalate_to_human",
        ),
        _s(
            "s3",
            "Unreadable? Hand to a human",
            "escalate_to_human",
            {
                "reason": f"Could not read the documents reliably (lowest confidence ${{{EXTRACT}.min_confidence}}).",
                "suggested_decision": "Check the documents manually.",
            },
            when=f"{EXTRACT}.low_confidence",
        ),
    ]
    if p.get("ids"):
        steps.append(
            _s("s4", "Validate identifiers", "validate_ids", {"fields": f"${EXTRACT}.fields", "ids": p["ids"]})
        )
    if p.get("compare"):
        steps.append(
            _s("s5", "Cross-check documents", "compare_fields", {"fields": f"${EXTRACT}.fields", "pairs": p["compare"]})
        )
    if p.get("formulas"):
        steps.append(
            _s(METRICS, "Compute metrics", "compute", {"fields": f"${EXTRACT}.fields", "formulas": p["formulas"]})
        )
    context = {}
    if p.get("classify"):
        c = p["classify"]
        steps.append(
            _s(
                CLASSIFY,
                "Classify the reason",
                "classify_text",
                {"text": _ref(c["text"]), "labels": c["labels"], "hints": c.get("hints", {})},
                retry=2,
            )
        )
        context["reason"] = f"${CLASSIFY}.label"
    if p.get("image"):
        only_if = p["image"].get("when_label")
        steps.append(
            _s(
                IMAGE,
                "Check the photo (Gemma vision)",
                "assess_image",
                {"image": f"${INTAKE}.photo", "question": p["image"]["question"]},
                retry=2,
                when=f"{CLASSIFY}.label == '{only_if}'" if only_if and p.get("classify") else None,
            )
        )
        context["photo"] = f"${IMAGE}.answer"
    steps.append(
        _s(
            "s9",
            "Apply SOP rules",
            "check_rules",
            {"fields": f"${EXTRACT}.fields", "metrics": metrics, "rules": p.get("rules", [])},
        )
    )
    steps.append(
        _s(
            DECIDE,
            "Decide route (decision table)",
            "decide",
            {
                "fields": f"${EXTRACT}.fields",
                "metrics": metrics,
                "context": context,
                "table": p["decision"],
                "default_route": p["default_route"],
            },
        )
    )
    counter = iter(range(11, 99))

    def nid() -> str:
        return f"s{next(counter)}"

    steps.append(
        _s(
            nid(),
            "Hand to a human (review)",
            "escalate_to_human",
            {
                "reason": f"${{{DECIDE}.reason}} Flags: ${{{DECIDE}.issues}}",
                "suggested_decision": "Check the evidence, then approve or reject.",
            },
            when=f"{DECIDE}.route == 'human_review'",
        )
    )
    appr = p.get("approval")
    if appr:
        cond = f"{DECIDE}.route == '{appr['route']}'" + (
            "" if appr.get("when") in (None, "true", True) else f" and ({_qualify(appr['when'], p)})"
        )
        roles = {d["key"]: d["role"] for d in p.get("directory", [])}
        steps.append(
            _s(
                nid(),
                f"Approval: {', '.join(roles.get(k, k) for k in appr['approvers'])}",
                "request_approval",
                {"approvers": [f"$org.people.{k}" for k in appr["approvers"]], "reason": appr.get("reason", "")},
                when=cond,
                approval=True,
            )
        )
    if p.get("refund"):
        r = p["refund"]
        steps.append(
            _s(
                nid(),
                "Issue refund",
                "issue_refund",
                {"reference": _ref(r["reference"]), "amount": _ref(r["amount"]), "to": _ref(r["to"])},
                when=f"{DECIDE}.route == '{r['route']}'",
            )
        )
    if p.get("requests"):
        rq = p["requests"]
        for item in rq["items"]:
            steps.append(
                _s(
                    nid(),
                    f"Raise {item['team']} request",
                    "create_request",
                    {"team": item["team"], "request": _text(item["request"])},
                    when=f"{DECIDE}.route == '{rq['route']}'",
                )
            )
    for route, spec in p["routes"].items():
        msg = spec.get("message")
        if not msg:
            continue
        did = nid()
        steps.append(
            _s(
                did,
                f"Draft message: {spec.get('label', route)}",
                "draft_message",
                {
                    "to_name": _ref(contact["name"]),
                    "purpose": msg["purpose"],
                    "facts": _text(msg["facts"]),
                    "language": _ref(contact["language"]) if contact.get("language") else "en",
                },
                when=f"{DECIDE}.route == '{route}'",
                retry=2,
            )
        )
        steps.append(
            _s(
                nid(),
                f"Send: {spec.get('label', route)}",
                "send_message",
                {"to": _ref(contact["email"]), "subject": f"${did}.subject", "body": f"${did}.body"},
                when=f"{DECIDE}.route == '{route}'",
            )
        )
    outcome_routes = [r for r, spec in p["routes"].items() if spec.get("outcome")]
    steps.append(
        _s(
            nid(),
            "Record outcome",
            "record_outcome",
            {
                "case_id": "$task.case_id",
                "outcome": f"${DECIDE}.route",
                "summary": f"${{{DECIDE}.route}}: ${{{DECIDE}.reason}}",
            },
            when=f"{DECIDE}.route in {outcome_routes!r}",
        )
    )
    return {
        "name": f"{p['department']} — {p['case_noun']} processing",
        "description": f"{p['employee']['title']}: reads each {p['case_noun']}, validates and cross-checks the "
        "documents, applies the SOP rules, decides the route, asks for approval where required "
        "and communicates the outcome.",
        "steps": steps,
    }
