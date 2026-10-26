"""Actions that change the outside world (books, payment batch, emails) and hand-offs to humans.
These are the steps autonomy levels control: simulated in Shadow, approved one by one in Supervised."""

from datetime import date, timedelta

from .. import company as co
from .. import db
from ..core.registry import ExecContext, action
from .finance import fmt_inr


def _output(ctx: ExecContext, kind: str, data: dict) -> dict:
    doc = {
        "id": db.new_id(kind[:3]),
        "kind": kind,
        "employee_id": ctx.employee.get("id"),
        "task_id": ctx.task.get("id"),
        "status": kind,
        "data": data,
    }
    db.put("outputs", doc)
    db.audit(ctx.employee.get("name", "employee"), kind, data.get("summary", ""), ctx.task.get("id"))
    return doc


def _next_friday(d: date | None = None) -> date:
    d = d or date.today()
    return d + timedelta(days=(4 - d.weekday()) % 7 or 7)


@action(
    "request_approval",
    roles=("*",),
    description="Pause and ask the named approver(s) to approve before continuing (human-in-the-loop).",
    inputs={"approvers": "list", "amount": "number?", "reason": "str?"},
    outputs={"approved": "bool", "approved_by": "str"},
)
def request_approval(ctx: ExecContext, approvers: list, amount: float | None = None, reason: str | None = None) -> dict:
    # the runner pauses BEFORE this runs (requires_approval); reaching here means a human said yes
    who = ", ".join(approvers or []) or "approver"
    return {"approved": True, "approved_by": who}


@action(
    "escalate_to_human",
    roles=("*",),
    halts=True,
    description="Stop and hand the task to a person in the review inbox with the reasons and evidence.",
    inputs={"reason": "str", "suggested_decision": "str?"},
    outputs={"inbox_id": "str", "reason": "str"},
)
def escalate_to_human(ctx: ExecContext, reason: str, suggested_decision: str | None = None) -> dict:
    item = {
        "id": db.new_id("inb"),
        "task_id": ctx.task.get("id"),
        "employee_id": ctx.employee.get("id"),
        "kind": "review",
        "status": "open",
        "title": f"Review: {ctx.task.get('title', '')}",
        "reason": reason,
        "payload": {
            "route": "human_review",
            "flags": ctx.flags,
            "suggested_decision": suggested_decision or "",
            "fields": None,
        },
    }
    db.put("inbox", item)
    return {"inbox_id": item["id"], "reason": reason}


@action(
    "reject_invoice",
    roles=("ap",),
    side_effect=True,
    description="Reject the invoice: record the rejection and draft a polite notice to the vendor with the reason.",
    inputs={"invoice": "dict", "reason": "str", "vendor_email": "str?"},
    outputs={"rejection_id": "str", "email_id": "str"},
)
def reject_invoice(ctx: ExecContext, invoice: dict, reason: str, vendor_email: str | None = None) -> dict:
    inv = invoice or {}
    rej = _output(
        ctx,
        "rejection",
        {
            "invoice_no": inv.get("invoice_no"),
            "vendor": inv.get("vendor_name"),
            "total": inv.get("total"),
            "reason": reason,
            "summary": f"Rejected {inv.get('invoice_no')} from {inv.get('vendor_name')}: {reason}",
        },
    )
    body = (
        f"Dear {inv.get('vendor_name')},\n\nWe are unable to process invoice {inv.get('invoice_no')} dated "
        f"{inv.get('invoice_date')} for {fmt_inr(inv.get('total'))}.\nReason: {reason}\n\n"
        "Please send a corrected invoice or contact accounts payable.\n\nRegards,\nAccounts Payable\n"
        f"{co.company().get('name')}"
    )
    email = _output(
        ctx,
        "email",
        {
            "to": vendor_email or "vendor",
            "subject": f"Invoice {inv.get('invoice_no')} not processed",
            "body": body,
            "summary": f"Rejection notice to {inv.get('vendor_name')}",
        },
    )
    return {"rejection_id": rej["id"], "email_id": email["id"]}


@action(
    "post_journal_entry",
    roles=("ap",),
    side_effect=True,
    money=True,
    description="Book the invoice in the accounts: Dr expense or inventory, Dr input GST, Cr vendor payable.",
    inputs={"invoice": "dict", "vendor_id": "str?", "category": "str", "inventory_categories": "list?"},
    outputs={"entry_id": "str", "lines": "list"},
)
def post_journal_entry(
    ctx: ExecContext,
    invoice: dict,
    category: str,
    vendor_id: str | None = None,
    inventory_categories: list | None = None,
) -> dict:
    inv = invoice or {}
    debit_acct = f"Inventory — {category}" if category in (inventory_categories or []) else f"Expense — {category}"
    lines = [{"account": debit_acct, "dr": inv.get("subtotal") or 0, "cr": 0}]
    for k in ("cgst", "sgst", "igst"):
        if inv.get(k):
            lines.append({"account": f"Input {k.upper()}", "dr": inv[k], "cr": 0})
    lines.append({"account": f"Sundry Creditors — {inv.get('vendor_name')}", "dr": 0, "cr": inv.get("total") or 0})
    entry = _output(
        ctx,
        "journal",
        {
            "invoice_no": inv.get("invoice_no"),
            "vendor_id": vendor_id,
            "lines": lines,
            "summary": f"Posted {inv.get('invoice_no')} {fmt_inr(inv.get('total'))} to {debit_acct}",
        },
    )
    return {"entry_id": entry["id"], "lines": lines}


@action(
    "add_to_payment_batch",
    roles=("ap",),
    side_effect=True,
    money=True,
    description="Schedule payment in the weekly Friday batch. Pays ONLY to the bank account on the vendor master, "
    "never to bank details printed on the invoice.",
    inputs={"invoice": "dict", "vendor_id": "str"},
    outputs={"batch_id": "str", "pay_on": "date", "amount": "number"},
)
def add_to_payment_batch(ctx: ExecContext, invoice: dict, vendor_id: str) -> dict:
    inv = invoice or {}
    v = co.vendor(vendor_id) or {}
    pay_on = _next_friday()
    batch_id = f"PAY-{pay_on.isoformat()}"
    _output(
        ctx,
        "payment",
        {
            "batch_id": batch_id,
            "pay_on": pay_on.isoformat(),
            "vendor_id": vendor_id,
            "vendor": v.get("name"),
            "amount": inv.get("total"),
            "bank_account": v.get("bank_account"),
            "ifsc": v.get("ifsc"),
            "invoice_no": inv.get("invoice_no"),
            "summary": f"{fmt_inr(inv.get('total'))} to {v.get('name')} in batch {batch_id}",
        },
    )
    return {"batch_id": batch_id, "pay_on": pay_on.isoformat(), "amount": inv.get("total")}


@action(
    "notify",
    roles=("*",),
    side_effect=True,
    description="Send an internal notification (e.g. to the finance manager) — written to the outbox.",
    inputs={"to": "str", "message": "str"},
    outputs={"message_id": "str"},
)
def notify(ctx: ExecContext, to: str, message: str) -> dict:
    doc = _output(
        ctx, "email", {"to": to, "subject": "Prompt2Process notification", "body": message, "summary": message[:120]}
    )
    return {"message_id": doc["id"]}
