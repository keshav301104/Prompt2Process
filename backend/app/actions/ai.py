"""Judgement steps: expense categorisation (learned model first, Gemma when unsure) and routing."""

from .. import company as co
from ..core.registry import ExecContext, action
from ..core.schema import REJECT_TYPES, REVIEW_TYPES
from ..learning import classifier
from ..llm.gemma import LLMUnavailable, llm
from ..safety import injection


def _keyword_guess(text: str, hints: dict, default: str | None) -> tuple[str | None, float]:
    t = text.lower()
    scores = {c: sum(t.count(k.lower()) for k in kws) for c, kws in (hints or {}).items()}
    if not scores or max(scores.values()) == 0:
        return default, 0.5
    best = max(scores, key=lambda c: scores[c])
    return best, min(0.9, 0.55 + 0.1 * scores[best])


@action(
    "classify_expense",
    roles=("ap",),
    description="Assign the expense category for booking. Uses the employee's learned model when it is confident "
    "(no AI call), otherwise asks Gemma 4; falls back to the vendor's default category.",
    inputs={"invoice": "dict", "categories": "list", "default_category": "str?", "hints": "dict?"},
    outputs={"category": "str", "confidence": "number", "source": "str"},
)
def classify_expense(
    ctx: ExecContext, invoice: dict, categories: list, default_category: str | None = None, hints: dict | None = None
) -> dict:
    inv = invoice or {}
    text = classifier.invoice_text(inv.get("vendor_name"), inv.get("line_items"))
    emp_id = ctx.employee.get("id", "")

    pred = classifier.predict(emp_id, text)
    cat: str | None
    if pred and pred[1] >= classifier.CONFIDENCE_THRESHOLD:
        classifier.note_saved_call(emp_id)
        cat, conf, src = pred[0], pred[1], "learned-model"
    else:
        try:
            ans = llm.generate_json(
                f"Classify this purchase invoice into exactly one expense category for {co.company().get('name') or 'the company'}"
                f" ({co.company().get('industry') or 'business'}). Categories: {', '.join(categories)}.\n"
                'Answer as JSON: {"category": "<one of the categories>", "confidence": <0..1>, "why": "<short>"}\n'
                + injection.wrap_document(text),
                purpose="classify_expense",
            )
            cat = ans.get("category") if ans.get("category") in categories else None
            conf, src = float(ans.get("confidence") or 0.7), "gemma"
            if not cat:
                cat, conf, src = (
                    (default_category or _keyword_guess(text, hints or {}, default_category)[0]),
                    0.5,
                    "vendor-default",
                )
        except (LLMUnavailable, ValueError):
            cat, conf = _keyword_guess(text, hints or {}, default_category)
            src = "keywords"
            if default_category and conf < 0.7:
                cat, conf, src = default_category, 0.7, "vendor-default"
        cat = cat or (categories[0] if categories else "Uncategorised")
    return {
        "category": cat,
        "confidence": round(conf, 2),
        "source": src,
        "text": text,
        "_fields": {"category": {"value": cat, "confidence": round(conf, 2), "source": src}},
    }


@action(
    "decide_route",
    roles=("ap",),
    description="Decide what happens to the invoice from everything found so far, using the SOP thresholds: "
    "reject (duplicate / invalid GSTIN) > human_review (any control failed) > approval (above the "
    "auto-post limit; dual approval above the second limit) > auto_post.",
    inputs={
        "total": "number",
        "auto_post_below": "number",
        "dual_approval_from": "number",
        "approver": "str",
        "second_approver": "str",
    },
    outputs={"route": "str", "reasons": "list", "approvers": "list", "issues": "list"},
)
def decide_route(
    ctx: ExecContext,
    total: float | None,
    auto_post_below: float,
    dual_approval_from: float,
    approver: str,
    second_approver: str,
) -> dict:
    types = {f["type"] for f in ctx.flags if f.get("severity") in ("warn", "critical")}
    approver = approver or "first approver (not set in the directory)"
    second_approver = second_approver or "second approver (not set in the directory)"
    total = float(total or 0)
    reasons, approvers = [], []
    if "low_confidence" in types:
        route = "human_review"
        reasons = ["The invoice could not be read reliably, so nothing can be decided automatically."]
    elif types & REJECT_TYPES:
        route = "reject"
        reasons = [f["message"] for f in ctx.flags if f["type"] in REJECT_TYPES]
    elif types & REVIEW_TYPES:
        route = "human_review"
        reasons = [f["message"] for f in ctx.flags if f["type"] in REVIEW_TYPES]
    elif total >= float(auto_post_below):
        route = "approval"
        approvers = [approver] + ([second_approver] if total >= float(dual_approval_from) else [])
        reasons = [f"₹{total:,.2f} is at or above the auto-post limit of ₹{float(auto_post_below):,.0f}"]
    else:
        route = "auto_post"
        reasons = [f"All controls passed and ₹{total:,.2f} is below ₹{float(auto_post_below):,.0f}"]
    return {
        "route": route,
        "reasons": reasons,
        "approvers": approvers,
        "issues": sorted(types),
        "_fields": {"route": {"value": route, "confidence": 1.0, "source": "rules"}},
    }
