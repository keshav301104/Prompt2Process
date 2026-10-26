"""Collections employee tools: customer lookup, late-payment risk, reminder ladder, multilingual drafting."""

from datetime import date, timedelta

from .. import company as co
from .. import db
from ..core.registry import ExecContext, action
from ..learning import risk as risk_model
from ..llm.gemma import LLMUnavailable, llm
from ..safety import pii

LANG_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu"}
TONES = {1: "friendly reminder", 2: "firm but polite reminder", 3: "final notice before escalation"}


@action(
    "load_customer",
    roles=("collections",),
    description="Load the overdue customer's record from the receivables ledger.",
    inputs={"customer_id": "str"},
    outputs={
        "customer_id": "str",
        "name": "str",
        "contact_person": "str",
        "email": "str",
        "phone": "str",
        "language": "str",
        "invoice_no": "str",
        "amount": "number",
        "due_date": "date",
        "days_overdue": "number",
        "avg_delay_days_history": "number",
        "broken_promises": "number",
        "last_reminder_level": "number",
        "customer_since_months": "number",
    },
)
def load_customer(ctx: ExecContext, customer_id: str) -> dict:
    c = next((r for r in co.ar_ledger() if r.get("customer_id") == customer_id), None)
    if not c:
        raise ValueError(f"customer {customer_id} not in ledger")
    out = {
        k: c.get(k)
        for k in (
            "customer_id",
            "name",
            "contact_person",
            "email",
            "phone",
            "language",
            "invoice_no",
            "amount",
            "due_date",
            "days_overdue",
            "avg_delay_days_history",
            "broken_promises",
            "last_reminder_level",
            "customer_since_months",
        )
    }
    out["_fields"] = {
        "customer": {"value": c.get("name"), "confidence": 1.0, "source": "ledger"},
        "amount": {"value": c.get("amount"), "confidence": 1.0, "source": "ledger"},
        "days_overdue": {"value": c.get("days_overdue"), "confidence": 1.0, "source": "ledger"},
        "language": {
            "value": LANG_NAMES.get(c.get("language") or "", c.get("language")),
            "confidence": 1.0,
            "source": "ledger",
        },
    }
    return out


@action(
    "score_payment_risk",
    roles=("collections",),
    description="Predict the probability this customer pays more than 30 days late (logistic regression trained "
    "on the company's payment history) and explain the main factors.",
    inputs={"customer": "dict"},
    outputs={"risk": "number", "label": "str", "top_factors": "list"},
)
def score_payment_risk(ctx: ExecContext, customer: dict) -> dict:
    r = risk_model.score(customer or {})
    flags = []
    if r["label"] == "high":
        flags.append(
            ctx.flag("high_risk", "warn", f"High late-payment risk ({r['risk']:.0%}).", "; ".join(r["top_factors"]))
        )
    r["_flags"] = flags
    r["_fields"] = {"risk": {"value": f"{r['risk']:.0%} ({r['label']})", "confidence": 1.0, "source": "risk-model"}}
    return r


@action(
    "choose_reminder_level",
    roles=("collections",),
    description="Pick the reminder level from the SOP ladder based on days overdue (never skip a level).",
    inputs={
        "days_overdue": "number",
        "last_level": "number?",
        "level1_days": "number?",
        "level2_days": "number?",
        "level3_days": "number?",
    },
    outputs={"level": "number", "tone": "str", "action_needed": "bool"},
)
def choose_reminder_level(
    ctx: ExecContext,
    days_overdue: float,
    last_level: float | None = 0,
    level1_days: float = 7,
    level2_days: float = 15,
    level3_days: float = 30,
) -> dict:
    d = float(days_overdue or 0)
    by_days = 3 if d >= level3_days else 2 if d >= level2_days else 1 if d >= level1_days else 0
    level = min(by_days, int(last_level or 0) + 1) if by_days else 0  # never jump more than one level
    if level <= int(last_level or 0) and by_days:
        level = int(last_level or 0)  # repeat current level
    return {
        "level": level,
        "tone": TONES.get(level, "no reminder yet"),
        "action_needed": level > 0,
        "_fields": {"reminder_level": {"value": level, "confidence": 1.0, "source": "rules"}},
    }


TEMPLATES = {
    "en": (
        "Payment reminder: invoice {inv}",
        "Dear {person},\n\n{opening} invoice {inv} for {amt} was due on {due} and is now {days} days overdue. "
        "We would be grateful if you could arrange the payment at the earliest, or let us know a date by which "
        "we can expect it.\n\nThank you for your continued partnership.\n\nWarm regards,\nAccounts Receivable\n{co}",
    ),
    "hi": (
        "भुगतान अनुस्मारक: इनवॉइस {inv}",
        "आदरणीय {person} जी,\n\n{opening_hi} इनवॉइस {inv} ({amt}) की देय तिथि {due} थी और अब यह {days} दिन से बकाया है। "
        "कृपया जल्द से जल्द भुगतान की व्यवस्था करें, या हमें वह तारीख बताएं जब तक भुगतान हो सकेगा।\n\n"
        "आपके सहयोग के लिए धन्यवाद।\n\nसादर,\nलेखा विभाग\n{co}",
    ),
}
OPENINGS = {
    1: "This is a gentle reminder that",
    2: "Despite our earlier reminder,",
    3: "This is our final notice before we escalate the matter:",
}
OPENINGS_HI = {
    1: "यह एक विनम्र अनुस्मारक है कि",
    2: "हमारे पिछले अनुस्मारक के बावजूद,",
    3: "यह मामले को आगे बढ़ाने से पहले हमारी अंतिम सूचना है:",
}


@action(
    "draft_reminder",
    roles=("collections",),
    description="Write the payment reminder in the customer's preferred language (English, Hindi, Telugu) with the "
    "tone required by the level. Never threatening or shaming. Uses Gemma 4; phone numbers and emails "
    "are masked before the model sees anything.",
    inputs={"customer": "dict", "level": "number", "language": "str?"},
    outputs={"subject": "str", "body": "str", "language": "str", "method": "str"},
)
def draft_reminder(ctx: ExecContext, customer: dict, level: float, language: str | None = None) -> dict:
    c = customer or {}
    lang = (language or c.get("language") or "en").lower()
    level = int(level or 1)
    amt = f"₹{float(c.get('amount') or 0):,.2f}"
    company_name = co.company().get("name")
    try:
        facts = (
            f"Customer: {c.get('name')} (contact: {c.get('contact_person')}, phone {c.get('phone')}, "
            f"email {c.get('email')}). Invoice {c.get('invoice_no')} for {amt}, due {c.get('due_date')}, "
            f"{int(c.get('days_overdue') or 0)} days overdue. Sender: Accounts Receivable, {company_name}."
        )
        masked, mapping = pii.mask(facts)
        ans = llm.generate_json(
            f"Write a {TONES.get(level, 'reminder')} for an overdue B2B invoice, in {LANG_NAMES.get(lang, 'English')} "
            f"(native script). Polite, respectful, never threatening or shaming, no legal threats. Ask for a payment "
            f"date. Keep it under 120 words. Facts:\n{masked}\n"
            'Return JSON: {"subject": "...", "body": "..."}',
            purpose="draft_reminder",
        )
        ans = pii.unmask(ans, mapping)
        subject, body, method = ans.get("subject", ""), ans.get("body", ""), "gemma"
    except (LLMUnavailable, ValueError):
        tmpl_lang = lang if lang in TEMPLATES else "en"
        subj, body_t = TEMPLATES[tmpl_lang]
        subject = subj.format(inv=c.get("invoice_no"))
        body = body_t.format(
            person=c.get("contact_person") or c.get("name"),
            inv=c.get("invoice_no"),
            amt=amt,
            due=c.get("due_date"),
            days=int(c.get("days_overdue") or 0),
            co=company_name,
            opening=OPENINGS.get(level, OPENINGS[1]),
            opening_hi=OPENINGS_HI.get(level, OPENINGS_HI[1]),
        )
        method = "template" if tmpl_lang == lang else "template (English — Telugu needs the live model)"
    return {
        "subject": subject,
        "body": body,
        "language": lang,
        "method": method,
        "_fields": {
            "draft_subject": {"value": subject, "confidence": 0.9, "source": method},
            "draft_body": {"value": body, "confidence": 0.9, "source": method},
        },
    }


@action(
    "send_reminder",
    roles=("collections",),
    side_effect=True,
    description="Send the reminder email to the customer (written to the outbox for this demo).",
    inputs={"to": "str", "subject": "str", "body": "str"},
    outputs={"message_id": "str"},
)
def send_reminder(ctx: ExecContext, to: str, subject: str, body: str) -> dict:
    doc = {
        "id": db.new_id("rem"),
        "kind": "reminder",
        "employee_id": ctx.employee.get("id"),
        "task_id": ctx.task.get("id"),
        "status": "reminder",
        "data": {"to": to, "subject": subject, "body": body, "summary": f"Reminder to {to}: {subject}"},
    }
    db.put("outputs", doc)
    db.audit(ctx.employee.get("name", "employee"), "reminder_sent", f"to {to}: {subject}", ctx.task.get("id"))
    return {"message_id": doc["id"]}


@action(
    "log_followup",
    roles=("collections",),
    side_effect=True,
    description="Record the reminder level sent and schedule the next follow-up date.",
    inputs={"customer_id": "str", "level": "number", "follow_up_in_days": "number?"},
    outputs={"next_follow_up": "date"},
)
def log_followup(ctx: ExecContext, customer_id: str, level: float, follow_up_in_days: float = 7) -> dict:
    nxt = (date.today() + timedelta(days=int(follow_up_in_days or 7))).isoformat()
    db.put(
        "outputs",
        {
            "id": db.new_id("fol"),
            "kind": "followup",
            "employee_id": ctx.employee.get("id"),
            "task_id": ctx.task.get("id"),
            "status": "followup",
            "data": {
                "customer_id": customer_id,
                "level": level,
                "next": nxt,
                "summary": f"Level {int(level)} logged for {customer_id}; follow up {nxt}",
            },
        },
    )
    return {"next_follow_up": nxt}
