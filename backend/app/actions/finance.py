"""Accounts-payable controls: vendor matching, GSTIN validation, tax/total arithmetic, duplicate detection,
three-way match (PO <-> goods receipt <-> invoice) and amount anomaly detection."""

import math
import re
from datetime import date

from rapidfuzz import fuzz

from .. import company as co
from .. import db
from ..core.registry import ExecContext, action
from ..learning import anomaly as anomaly_model

GSTIN_RE = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(g14: str) -> str:
    total = 0
    for i, c in enumerate(g14):
        p = _CH.index(c) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _CH[(36 - total % 36) % 36]


def fmt_inr(x: float | None) -> str:
    if x is None:
        return "—"
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"₹{'-' if x < 0 else ''}{whole}.{frac}"


# ------------------------------------------------------------------------------------ match_vendor
@action(
    "match_vendor",
    roles=("ap",),
    description="Match the invoice's vendor to the vendor master using GSTIN first, then fuzzy name/alias "
    "matching. Unknown vendors are flagged for review.",
    inputs={"name": "str", "gstin": "str?"},
    outputs={
        "vendor_id": "str",
        "vendor_name": "str",
        "known": "bool",
        "score": "number",
        "method": "str",
        "state_code": "str",
        "default_category": "str",
        "payment_terms_days": "number",
        "bank_account_on_file": "str",
        "ifsc_on_file": "str",
    },
)
def match_vendor(ctx: ExecContext, name: str, gstin: str | None = None) -> dict:
    best, score, method = None, 0.0, "none"
    if gstin:
        best = next((v for v in co.vendors() if v["gstin"] == gstin), None)
        if best:
            score, method = 100.0, "gstin"
    if not best and name:
        target = co.norm_name(name)
        for v in co.vendors():
            for cand in [v["name"]] + v["alias_list"]:
                s = fuzz.token_sort_ratio(target, co.norm_name(cand))
                if s > score:
                    best, score, method = v, s, "fuzzy-name"
        if score < 88:
            best = None
    flags = []
    if not best:
        flags.append(
            ctx.flag(
                "unknown_vendor",
                "warn",
                f"'{name}' is not in the vendor master (best match score {score:.0f}).",
                f"GSTIN on invoice: {gstin or '—'}",
            )
        )
        return {
            "vendor_id": None,
            "vendor_name": name,
            "known": False,
            "score": round(score, 1),
            "method": method,
            "state_code": (gstin or "")[:2],
            "default_category": None,
            "payment_terms_days": 30,
            "bank_account_on_file": None,
            "ifsc_on_file": None,
            "_flags": flags,
        }
    gstin_ok = bool(gstin and GSTIN_RE.match(gstin) and gstin_check_digit(gstin[:14]) == gstin[14])
    if method == "fuzzy-name" and gstin and gstin != best["gstin"] and gstin_ok:
        flags.append(
            ctx.flag(
                "unknown_vendor",
                "warn",
                f"Name matches {best['name']} but the GSTIN differs from the master record.",
                f"invoice {gstin} vs master {best['gstin']}",
            )
        )
    return {
        "vendor_id": best["vendor_id"],
        "vendor_name": best["name"],
        "known": not flags,
        "score": round(score, 1),
        "method": method,
        "state_code": best["state_code"],
        "default_category": best.get("default_category"),
        "payment_terms_days": best["payment_terms_days"],
        "bank_account_on_file": best.get("bank_account"),
        "ifsc_on_file": best.get("ifsc"),
        "_flags": flags,
    }


# ------------------------------------------------------------------------------------ validate_gstin
@action(
    "validate_gstin",
    roles=("ap",),
    description="Validate a GSTIN: format, state code and the mod-36 check digit. Invalid GSTINs are flagged.",
    inputs={"gstin": "str"},
    outputs={"valid": "bool", "reason": "str", "state_code": "str", "pan": "str"},
)
def validate_gstin(ctx: ExecContext, gstin: str | None) -> dict:
    g = (gstin or "").strip().upper()
    reason = "ok"
    if not g:
        reason = "missing"
    elif not GSTIN_RE.match(g):
        reason = "bad format"
    elif not (1 <= int(g[:2]) <= 38 or g[:2] in ("97", "99")):
        reason = f"unknown state code {g[:2]}"
    elif gstin_check_digit(g[:14]) != g[14]:
        reason = f"check digit should be {gstin_check_digit(g[:14])}, found {g[14]}"
    valid = reason == "ok"
    if reason == "missing":
        flags = [
            ctx.flag(
                "gstin_missing", "warn", "No vendor GSTIN on the invoice — input tax credit cannot be claimed.", "—"
            )
        ]
    else:
        flags = [] if valid else [ctx.flag("gstin_invalid", "critical", f"Vendor GSTIN is invalid ({reason}).", g)]
    return {
        "valid": valid,
        "reason": reason,
        "state_code": g[:2],
        "pan": g[2:12] if len(g) >= 12 else "",
        "_flags": flags,
    }


# ------------------------------------------------------------------------------------ check_totals
@action(
    "check_totals",
    roles=("ap",),
    description="Verify the invoice arithmetic (qty x rate, line sum vs subtotal, tax amounts, grand total) and "
    "that the tax type is right: CGST+SGST within the same state, IGST across states.",
    inputs={"invoice": "dict", "buyer_state": "str?"},
    outputs={"ok": "bool", "issues": "list", "intra_state": "bool"},
)
def check_totals(ctx: ExecContext, invoice: dict, buyer_state: str | None = None) -> dict:
    inv = invoice or {}
    buyer_state = buyer_state or co.company().get("state_code") or ""
    issues, flags = [], []
    items = inv.get("line_items") or []
    for i, it in enumerate(items, 1):
        if it.get("qty") is not None and it.get("rate") is not None and it.get("amount") is not None:
            if abs(it["qty"] * it["rate"] - it["amount"]) > 1.0:
                issues.append(f"line {i}: {it['qty']} x {it['rate']} != {it['amount']}")
    sub, tot = inv.get("subtotal"), inv.get("total")
    line_sum = round(sum(it.get("amount") or 0 for it in items), 2)
    if sub is not None and items and abs(line_sum - sub) > 1.0:
        issues.append(f"lines add up to {fmt_inr(line_sum)} but subtotal says {fmt_inr(sub)}")
    tax = sum(inv.get(k) or 0 for k in ("cgst", "sgst", "igst"))
    if sub is not None and tot is not None and abs(sub + tax - tot) > 1.0:
        issues.append(f"subtotal + tax = {fmt_inr(sub + tax)} but total says {fmt_inr(tot)}")
    for k in ("cgst", "sgst", "igst"):
        r = inv.get(f"{k}_rate")
        if r and sub and inv.get(k) is not None and abs(sub * r / 100 - inv[k]) > 1.0:
            issues.append(f"{k.upper()} @{r}% should be {fmt_inr(sub * r / 100)}, invoice says {fmt_inr(inv[k])}")
    if issues:
        flags.append(ctx.flag("totals_mismatch", "warn", "Invoice arithmetic does not add up.", "; ".join(issues)))

    vendor_state = (inv.get("vendor_gstin") or "")[:2]
    intra = vendor_state == buyer_state
    has_cs = (inv.get("cgst") or 0) > 0 or (inv.get("sgst") or 0) > 0
    has_i = (inv.get("igst") or 0) > 0
    tax_issue = None
    if vendor_state and intra and has_i:
        tax_issue = f"IGST charged on an intra-state supply (vendor state {vendor_state} = buyer state {buyer_state})"
    elif vendor_state and not intra and has_cs:
        tax_issue = f"CGST/SGST charged on an inter-state supply (vendor state {vendor_state}, buyer {buyer_state})"
    if tax_issue:
        issues.append(tax_issue)
        flags.append(ctx.flag("tax_type_mismatch", "warn", "Wrong GST type for this supply.", tax_issue))
    return {"ok": not issues, "issues": issues, "intra_state": intra, "_flags": flags}


# ------------------------------------------------------------------------------------ check_duplicate
def _norm_invno(s: str | None) -> tuple:
    s = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    m = re.match(r"^(.*?)(\d+)$", s)
    return (m.group(1), int(m.group(2))) if m else (s, -1)


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _prior_invoices(ctx: ExecContext) -> list[dict]:
    rows = [dict(r, source="posted ledger") for r in co.posted_invoices()]
    if ctx.seen is not None:
        rows += [dict(r, source="earlier in this batch") for r in ctx.seen]
    else:
        for t in db.query("tasks", employee_id=ctx.employee.get("id"), status="done", limit=500):
            if t["id"] == ctx.task.get("id") or (t.get("outcome") or {}).get("final_decision") != "posted":
                continue
            f = t.get("fields") or {}
            rows.append(
                {
                    "vendor_id": (t.get("ref") or {}).get("vendor_id"),
                    "vendor_name": (f.get("vendor_name") or {}).get("value"),
                    "invoice_no": (f.get("invoice_no") or {}).get("value"),
                    "total": (f.get("total") or {}).get("value"),
                    "invoice_date": (f.get("invoice_date") or {}).get("value"),
                    "source": "posted by Prompt2Process",
                }
            )
    return rows


@action(
    "check_duplicate",
    roles=("ap",),
    description="Check whether this invoice was already posted or paid: same vendor and same invoice number "
    "(ignoring formatting like INV-0045 vs INV/45), or same vendor + same amount within 3 days.",
    inputs={"invoice": "dict", "vendor_id": "str?"},
    outputs={"is_duplicate": "bool", "matched": "dict", "reason": "str"},
)
def check_duplicate(ctx: ExecContext, invoice: dict, vendor_id: str | None = None) -> dict:
    inv = invoice or {}
    key = _norm_invno(inv.get("invoice_no"))
    d0 = _d(inv.get("invoice_date"))
    for r in _prior_invoices(ctx):
        same_vendor = (vendor_id and r.get("vendor_id") == vendor_id) or (
            fuzz.token_sort_ratio(co.norm_name(r.get("vendor_name")), co.norm_name(inv.get("vendor_name"))) >= 90
        )
        if not same_vendor:
            continue
        same_no = key[1] >= 0 and _norm_invno(r.get("invoice_no")) == key
        same_no = same_no or (
            key[1] >= 0
            and _norm_invno(r.get("invoice_no"))[1] == key[1]
            and abs((co.num(r.get("total")) or 0) - (inv.get("total") or -1)) < 1
        )
        d1 = _d(r.get("invoice_date"))
        near = d0 and d1 and abs((d0 - d1).days) <= 3
        same_amt_date = near and abs((co.num(r.get("total")) or 0) - (inv.get("total") or -1)) < 1
        if same_no or same_amt_date:
            reason = "same invoice number" if same_no else "same vendor, same amount, within 3 days"
            ev = f"{r.get('invoice_no')} · {fmt_inr(co.num(r.get('total')))} · {r.get('invoice_date')} ({r.get('source')})"
            return {
                "is_duplicate": True,
                "matched": {k: r.get(k) for k in ("invoice_no", "total", "invoice_date", "source")},
                "reason": reason,
                "_flags": [ctx.flag("duplicate", "critical", f"Possible duplicate: {reason}.", ev)],
            }
    return {"is_duplicate": False, "matched": {}, "reason": "no match"}


# ------------------------------------------------------------------------------------ three_way_match
@action(
    "three_way_match",
    roles=("ap",),
    description="Three-way match: compare the invoice against its purchase order (vendor, item rates) and goods "
    "receipts (quantities actually received). Flags overbilling beyond the rate tolerance, billing for "
    "more than was received, and goods invoices without a PO.",
    inputs={
        "invoice": "dict",
        "vendor_id": "str?",
        "category": "str?",
        "rate_tolerance_pct": "number?",
        "po_required_above": "number?",
        "goods_categories": "list?",
    },
    outputs={"status": "str", "issues": "list", "details": "list", "po_number": "str"},
)
def three_way_match(
    ctx: ExecContext,
    invoice: dict,
    vendor_id: str | None = None,
    category: str | None = None,
    rate_tolerance_pct: float = 2.0,
    po_required_above: float = 25000,
    goods_categories: list | None = None,
) -> dict:
    goods = set(goods_categories or [])
    inv = invoice or {}
    po_no = inv.get("po_number")
    flags, issues, details = [], [], []
    rate_tolerance_pct = float(rate_tolerance_pct or 2.0)
    if not po_no:
        is_goods = (category in goods) if category else True
        if is_goods or (inv.get("total") or 0) >= float(po_required_above or 25000):
            msg = (
                f"No purchase order on a {category or 'goods'} invoice of {fmt_inr(inv.get('total'))}. "
                "SOP requires a PO."
            )
            flags.append(ctx.flag("missing_po", "warn", msg, "PO Number: N/A"))
            return {"status": "missing_po", "issues": [msg], "details": [], "po_number": None, "_flags": flags}
        return {"status": "not_required", "issues": [], "details": ["Service below PO threshold"], "po_number": None}

    po = co.purchase_orders().get(po_no)
    if not po:
        msg = f"PO {po_no} not found in the purchase-order register."
        flags.append(ctx.flag("missing_po", "warn", msg, po_no))
        return {"status": "po_not_found", "issues": [msg], "details": [], "po_number": po_no, "_flags": flags}
    if vendor_id and po.get("vendor_id") != vendor_id:
        msg = f"PO {po_no} belongs to vendor {po.get('vendor_id')}, not {vendor_id}."
        issues.append(msg)
        flags.append(ctx.flag("po_vendor_mismatch", "warn", msg, po_no))

    received: dict[str, float] = {}
    for g in co.grns_by_po().get(po_no, []):
        for ln in g.get("lines", []):
            received[ln["item"]] = received.get(ln["item"], 0) + float(ln.get("qty_received") or 0)

    for it in inv.get("line_items") or []:
        desc = it.get("description") or ""
        best = max(po.get("lines", []), key=lambda p: fuzz.token_set_ratio(desc, p["item"]), default=None)
        if not best or fuzz.token_set_ratio(desc, best["item"]) < 70:
            msg = f"'{desc}' is not on PO {po_no}."
            issues.append(msg)
            flags.append(ctx.flag("overbilling", "warn", "Billed item not on the purchase order.", msg))
            continue
        po_rate, inv_rate = float(best["rate"]), float(it.get("rate") or 0)
        diff = (inv_rate - po_rate) / po_rate * 100 if po_rate else 0
        details.append(f"{best['item']}: rate {fmt_inr(inv_rate)} vs PO {fmt_inr(po_rate)} ({diff:+.1f}%)")
        if diff > rate_tolerance_pct:
            excess = (inv_rate - po_rate) * (it.get("qty") or 0)
            msg = (
                f"{best['item']}: billed {fmt_inr(inv_rate)}/unit vs PO {fmt_inr(po_rate)} (+{diff:.1f}%, "
                f"tolerance {rate_tolerance_pct:g}%). Excess {fmt_inr(excess)}."
            )
            issues.append(msg)
            flags.append(ctx.flag("overbilling", "warn", "Rate above the purchase order.", msg))
        rec = received.get(best["item"])
        qty = float(it.get("qty") or 0)
        if rec is None:
            if best["item"] not in received and po.get("lines") and (category in goods or not category):
                msg = f"No goods receipt recorded for {best['item']} on {po_no}."
                issues.append(msg)
                flags.append(ctx.flag("qty_mismatch", "warn", "Billed before goods were received.", msg))
        elif qty > rec + 1e-6:
            msg = f"{best['item']}: billed {qty:g} but only {rec:g} received (GRN)."
            issues.append(msg)
            flags.append(ctx.flag("qty_mismatch", "warn", "Billed quantity exceeds quantity received.", msg))
    return {
        "status": "matched" if not issues else "mismatch",
        "issues": issues,
        "details": details,
        "po_number": po_no,
        "_flags": flags,
    }


# ------------------------------------------------------------------------------------ score_anomaly
@action(
    "score_anomaly",
    roles=("ap",),
    description="Score how unusual the invoice amount is for this vendor (ratio to the vendor's historical "
    "median plus an Isolation Forest over the company ledger). Explains why.",
    inputs={"invoice": "dict", "vendor_id": "str?", "max_ratio": "number?"},
    outputs={
        "is_anomaly": "bool",
        "score": "number",
        "ratio_to_median": "number",
        "vendor_median": "number",
        "reason": "str",
    },
)
def score_anomaly(ctx: ExecContext, invoice: dict, vendor_id: str | None = None, max_ratio: float = 4.0) -> dict:
    total = (invoice or {}).get("total")
    if not total or not vendor_id:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "ratio_to_median": None,
            "vendor_median": None,
            "reason": "not enough information",
        }
    res = anomaly_model.score(vendor_id, float(total), float(max_ratio or 4.0))
    flags = []
    if res["is_anomaly"]:
        flags.append(ctx.flag("anomaly", "warn", "Amount is unusual for this vendor.", res["reason"]))
    res["_flags"] = flags
    return res


def months_between(a: str, b: str) -> float:
    da, dbb = _d(a), _d(b)
    return abs((da - dbb).days) / 30.4 if da and dbb else math.nan
