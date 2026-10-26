"""General skills — sector-agnostic tools every digital employee can use (roles = "*").

With these, a new department or sector needs only an SOP + a pack definition (data), not new code:
open a case, read its documents into a schema, validate Indian identifiers, cross-check documents,
compute metrics, apply rules, decide a route, look at a photo, draft and send messages, record outcomes.
"""

import re
from pathlib import Path
from typing import Any

import pymupdf
from rapidfuzz import fuzz

from .. import company as co
from .. import db
from ..core import expr
from ..core.registry import ExecContext, TransientError, action
from ..llm.gemma import LLMUnavailable, llm
from ..safety import injection, pii
from .finance import GSTIN_RE, fmt_inr, gstin_check_digit

ALL = ("*",)


# ------------------------------------------------------------------------------------ intake
def _read(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            return "\n".join(p.get_text() for p in doc)
    return path.read_text(encoding="utf-8", errors="ignore")


@action(
    "intake_case",
    roles=ALL,
    description="Open a case folder (an application, claim, request…): read every document in it, note which "
    "required documents are missing, find any photo, and screen all text for hidden instructions.",
    inputs={"folder": "str", "required_documents": "list?"},
    outputs={
        "documents": "dict",
        "doc_types": "list",
        "files": "list",
        "missing": "list",
        "photo": "str",
        "has_photo": "bool",
        "injection_detected": "bool",
    },
)
def intake_case(ctx: ExecContext, folder: str, required_documents: list | None = None) -> dict:
    base = co.safe_path(folder)
    if not base.exists():
        raise ValueError(f"case folder '{folder}' not found")
    docs, files, photo = {}, [], ""
    for p in sorted(base.iterdir()):
        rel = str(p.relative_to(co.DATA_DIR)).replace("\\", "/")
        if p.suffix.lower() in (".pdf", ".txt", ".md"):
            docs[p.stem] = _read(p)
            files.append(rel)
        elif p.suffix.lower() in (".png", ".jpg", ".jpeg") and not photo:
            photo = rel
            files.append(rel)
    missing = [d for d in (required_documents or []) if d not in docs]
    flags = []
    if missing:
        flags.append(
            ctx.flag(
                "missing_documents",
                "warn",
                f"Missing required document(s): {', '.join(missing)}.",
                f"received: {', '.join(docs) or 'none'}",
            )
        )
    scan = injection.scan("\n".join(docs.values()))
    if scan["detected"]:
        flags.append(
            ctx.flag(
                "injection",
                "critical",
                "Instruction-like text found inside a document. Treated as data, not obeyed.",
                scan["hits"][0]["snippet"] if scan["hits"] else "",
            )
        )
    return {
        "documents": docs,
        "doc_types": sorted(docs),
        "files": files,
        "missing": missing,
        "photo": photo,
        "has_photo": bool(photo),
        "injection_detected": scan["detected"],
        "_flags": flags,
    }


# ------------------------------------------------------------------------------------ extraction
def _convert(raw: str | None, typ: str):
    if raw is None:
        return None
    raw = raw.strip()
    if typ == "number":
        m = re.search(r"-?[\d,]+(?:\.\d+)?", raw.replace("₹", "").replace("Rs.", ""))
        return co.num(m.group(0)) if m else None
    if typ == "date":
        from .documents import _date

        return _date(raw) or raw
    if typ == "bool":
        return raw.lower() in ("yes", "y", "true", "signed", "1")
    return raw


def _template_extract(documents: dict, schema: dict) -> tuple[dict[str, dict], dict[str, float | None]]:
    fields: dict[str, dict] = {}
    conf: dict[str, float | None] = {}
    for dtype, spec in schema.items():
        text = documents.get(dtype)
        fields[dtype] = {}
        for key, f in spec.items():
            label = re.escape(f.get("label", key))
            m = re.search(rf"^\s*{label}\s*:\s*(.+?)\s*$", text or "", re.MULTILINE | re.IGNORECASE) if text else None
            fields[dtype][key] = _convert(m.group(1) if m else None, f.get("type", "str"))
            conf[f"{dtype}.{key}"] = 0.98 if m else (0.0 if text else None)
    return fields, conf


def _gemma_extract(documents: dict, schema: dict) -> tuple[dict, dict]:
    want = {
        d: {k: f"{f.get('label', k)} ({f.get('type', 'str')})" for k, f in spec.items()} for d, spec in schema.items()
    }
    body = "\n\n".join(f"### {d}\n{t}" for d, t in documents.items() if d in schema)
    masked, mapping = pii.mask(body, keep=("GSTIN", "PAN", "IFSC"))
    ans = llm.generate_json(
        'Extract these fields from the documents below. Output JSON: {"fields": {<document type>: {<field>: value}}, '
        '"confidence": {<document type>.<field>: 0..1}}. Numbers as plain numbers, dates as YYYY-MM-DD, null if absent.\n'
        f"Fields wanted: {want}\n" + injection.wrap_document(masked),
        purpose="extract_case",
    )
    ans = pii.unmask(ans, mapping)
    fields = {
        d: {
            k: _convert(str(v), schema[d][k].get("type", "str")) if v is not None else None
            for k, v in (ans.get("fields", {}).get(d) or {}).items()
            if k in schema[d]
        }
        for d in schema
    }
    conf = {k: float(v) for k, v in (ans.get("confidence") or {}).items() if isinstance(v, (int, float))}
    return fields, conf


@action(
    "extract_case",
    roles=ALL,
    description="Read every document of the case into a structured schema {document_type: {field: value}} with a "
    "confidence per field. Fast label parser first, Gemma 4 when the layout is unusual. "
    "Personal identifiers are masked before any model call.",
    inputs={"documents": "dict", "schema": "dict"},
    outputs={
        "fields": "dict",
        "confidence": "dict",
        "method": "str",
        "min_confidence": "number",
        "low_confidence": "bool",
    },
)
def extract_case(ctx: ExecContext, documents: dict, schema: dict) -> dict:
    documents = documents or {}
    mode = ctx.settings.get("extraction_mode", "template_first")
    fields: dict[str, dict] = {}
    conf: dict[str, float | None] = {}
    method = "template"
    if mode == "template_first":
        fields, conf = _template_extract(documents, schema)
    key_missing = [
        f"{d}.{k}"
        for d, spec in schema.items()
        if d in documents
        for k, f in spec.items()
        if f.get("key") and fields.get(d, {}).get(k) is None
    ]
    if mode != "template_first" or key_missing:
        try:
            g_fields, g_conf = _gemma_extract(documents, schema)
            for d, vals in g_fields.items():
                for k, v in vals.items():
                    if fields.get(d, {}).get(k) is None and v is not None:
                        fields.setdefault(d, {})[k] = v
                        conf[f"{d}.{k}"] = min(g_conf.get(f"{d}.{k}", 0.85), 0.95)
            method = "gemma" if mode != "template_first" else "template+gemma"
        except (LLMUnavailable, ValueError) as e:
            if isinstance(e, ValueError):
                raise TransientError(f"model returned unreadable JSON: {e}") from e
    key_conf = [
        conf.get(f"{d}.{k}") or 0.0
        for d, spec in schema.items()
        if d in documents
        for k, f in spec.items()
        if f.get("key")
    ]
    min_conf = round(min(key_conf), 2) if key_conf else 1.0
    low = min_conf < 0.8
    flags = []
    if low:
        weak = [
            f"{d}.{k}"
            for d, spec in schema.items()
            if d in documents
            for k, f in spec.items()
            if f.get("key") and (conf.get(f"{d}.{k}") or 0) < 0.8
        ]
        flags.append(
            ctx.flag(
                "low_confidence",
                "warn",
                f"Could not read {', '.join(weak)} reliably.",
                f"min confidence {min_conf:.2f} ({method})",
            )
        )
    task_fields = {}
    for d, spec in schema.items():
        for k, f in spec.items():
            if f.get("show") or f.get("key"):
                v = fields.get(d, {}).get(k)
                if v is not None:
                    task_fields[f.get("label", k)] = {
                        "value": v,
                        "confidence": conf.get(f"{d}.{k}") or 0.0,
                        "source": method.split("+")[-1],
                    }
    return {
        "fields": fields,
        "confidence": conf,
        "method": method,
        "min_confidence": min_conf,
        "low_confidence": low,
        "_flags": flags,
        "_fields": task_fields,
    }


# ------------------------------------------------------------------------------------ identifiers
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def validate_id(kind: str, value) -> tuple[bool, str]:
    v = re.sub(r"\s", "", str(value or "")).upper()
    if not v:
        return False, "missing"
    if kind == "pan":
        return (bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v)), "format AAAAA9999A")
    if kind == "ifsc":
        return (bool(re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v)), "format AAAA0XXXXXX")
    if kind == "gstin":
        ok = bool(GSTIN_RE.fullmatch(v)) and gstin_check_digit(v[:14]) == v[14]
        return ok, "format + check digit"
    if kind == "aadhaar":
        return (bool(re.fullmatch(r"[2-9][0-9]{11}", v)) and _verhoeff_ok(v), "12 digits + Verhoeff check")
    if kind == "phone":
        return (bool(re.fullmatch(r"(\+91)?[6-9][0-9]{9}", v)), "10-digit Indian mobile")
    if kind == "email":
        return (bool(re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", v, re.IGNORECASE)), "email format")
    if kind == "pincode":
        return (bool(re.fullmatch(r"[1-9][0-9]{5}", v)), "6-digit PIN")
    return True, "unchecked"


def _get_path(fields: dict, path: str) -> Any:
    cur: Any = fields
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


@action(
    "validate_ids",
    roles=ALL,
    description="Validate Indian identifiers found in the documents: PAN, IFSC, GSTIN (check digit), Aadhaar "
    "(Verhoeff check), mobile, email, PIN code. Each invalid one is flagged.",
    inputs={"fields": "dict", "ids": "list"},
    outputs={"valid": "bool", "invalid": "list"},
)
def validate_ids(ctx: ExecContext, fields: dict, ids: list) -> dict:
    invalid, flags = [], []
    for spec in ids or []:
        val = _get_path(fields or {}, spec["path"])
        if val is None and not spec.get("required", True):
            continue
        ok, rule = validate_id(spec["kind"], val)
        if not ok:
            masked = str(val)[:2] + "•••" + str(val)[-2:] if val and len(str(val)) > 5 else str(val)
            invalid.append(spec["path"])
            flags.append(
                ctx.flag(
                    f"invalid_{spec['kind']}",
                    spec.get("severity", "warn"),
                    f"{spec.get('label', spec['path'])} is not a valid {spec['kind'].upper()} ({rule}).",
                    masked,
                )
            )
    return {"valid": not invalid, "invalid": invalid, "_flags": flags}


# ------------------------------------------------------------------------------------ cross-checks
@action(
    "compare_fields",
    roles=ALL,
    description="Cross-check the same fact across documents (names, numbers, dates): fuzzy name match, numeric "
    "tolerance, exact match. Every disagreement is flagged with both values as evidence.",
    inputs={"fields": "dict", "pairs": "list"},
    outputs={"consistent": "bool", "mismatches": "list"},
)
def compare_fields(ctx: ExecContext, fields: dict, pairs: list) -> dict:
    mismatches, flags = [], []
    for p in pairs or []:
        a, b = _get_path(fields or {}, p["a"]), _get_path(fields or {}, p["b"])
        if a is None or b is None:
            continue
        kind = p.get("kind", "exact")
        if kind == "name":
            score = fuzz.token_sort_ratio(co.norm_name(str(a)), co.norm_name(str(b)))
            bad = score < p.get("min_score", 85)
            detail = f"'{a}' vs '{b}' (similarity {score:.0f})"
        elif kind == "number":
            fa, fb = float(a), float(b)
            tol = float(p.get("tolerance", 0.02))
            bad = abs(fa - fb) > tol * max(abs(fa), abs(fb), 1)
            detail = f"{fa:,.2f} vs {fb:,.2f} (tolerance {tol:.0%})"
        else:
            bad = str(a).strip().upper() != str(b).strip().upper()
            detail = f"'{a}' vs '{b}'"
        if bad:
            mismatches.append({"a": p["a"], "b": p["b"], "detail": detail})
            flags.append(
                ctx.flag(
                    p.get("issue", "document_mismatch"),
                    p.get("severity", "warn"),
                    p.get("message", f"{p['a']} does not match {p['b']}."),
                    detail,
                )
            )
    return {"consistent": not mismatches, "mismatches": mismatches, "_flags": flags}


@action(
    "compute",
    roles=ALL,
    description="Compute metrics from document fields with safe formulas (e.g. EMI, debt-to-income ratio, days "
    "between dates, payable amount). Later formulas may use earlier results by name.",
    inputs={"fields": "dict", "formulas": "dict"},
    outputs={"values": "dict"},
)
def compute(ctx: ExecContext, fields: dict, formulas: dict) -> dict:
    scope = dict(fields or {})
    values = {}
    for name, f in (formulas or {}).items():
        try:
            v = expr.compute(f, scope)
        except expr.ExprError as e:
            raise ValueError(f"formula '{name}': {e}") from e
        values[name] = round(v, 4) if isinstance(v, float) else v
        scope[name] = values[name]
    shown = {
        k: {"value": (round(v, 2) if isinstance(v, float) else v), "confidence": 1.0, "source": "formula"}
        for k, v in values.items()
        if v is not None
    }
    return {"values": values, "_fields": shown}


@action(
    "check_rules",
    roles=ALL,
    description="Apply the SOP's rules. Each rule is a safe condition that must hold (e.g. 'marksheet.cgpa >= 8'); "
    "every failed rule raises a flag with its message and the values it used.",
    inputs={"fields": "dict", "metrics": "dict?", "rules": "list"},
    outputs={"passed": "bool", "failed": "list", "issues": "list"},
)
def check_rules(ctx: ExecContext, fields: dict, rules: list, metrics: dict | None = None) -> dict:
    scope = {**(fields or {}), **(metrics or {})}
    failed, issues, flags = [], [], []
    for r in rules or []:
        try:
            refs = expr.references(r["check"])
            values = {".".join(p): expr.compute(".".join(p), scope) for p in refs}
            if any(v is None for v in values.values()) and r.get("skip_if_missing", True):
                continue
            ok = expr.evaluate(r["check"], scope)
        except expr.ExprError as e:
            raise ValueError(f"rule '{r.get('id')}': {e}") from e
        if not ok:
            failed.append(r.get("id"))
            issues.append(r["issue"])
            ev = ", ".join(
                f"{k} = {fmt_inr(v) if isinstance(v, (int, float)) and r.get('money') else v}"
                for k, v in values.items()
            )
            flags.append(ctx.flag(r["issue"], r.get("severity", "warn"), r.get("message", r["check"]), ev))
    return {"passed": not failed, "failed": failed, "issues": sorted(set(issues)), "_flags": flags}


# ------------------------------------------------------------------------------------ judgement
@action(
    "classify_text",
    roles=ALL,
    description="Classify free text (a reason, a complaint, a note) into one of the given labels. Gemma 4 when "
    "available, keyword hints otherwise.",
    inputs={"text": "str", "labels": "list", "hints": "dict?"},
    outputs={"label": "str", "confidence": "number", "source": "str"},
)
def classify_text(ctx: ExecContext, text: str, labels: list, hints: dict | None = None) -> dict:
    t = (text or "").lower()
    try:
        ans = llm.generate_json(
            f"Classify the text into exactly one label from {labels}. "
            'Return JSON {"label": "...", "confidence": 0..1}.\n' + injection.wrap_document(text or ""),
            purpose="classify_text",
        )
        if ans.get("label") in labels:
            return {"label": ans["label"], "confidence": float(ans.get("confidence") or 0.8), "source": "gemma"}
    except (LLMUnavailable, ValueError):
        pass
    scores = {lab: sum(t.count(k.lower()) for k in (hints or {}).get(lab, [lab])) for lab in labels}
    best = max(scores, key=lambda lab: scores[lab])
    return {
        "label": best if scores[best] else labels[-1],
        "confidence": 0.75 if scores[best] else 0.4,
        "source": "keywords",
    }


@action(
    "assess_image",
    roles=ALL,
    description="Look at a photo with Gemma 4 vision and answer a yes/no question about it (e.g. 'Is the product "
    "visibly damaged?'), with a short observation. Unclear answers are flagged for a human.",
    inputs={"image": "str", "question": "str"},
    outputs={"answer": "str", "confidence": "number", "observation": "str"},
)
def assess_image(ctx: ExecContext, image: str, question: str) -> dict:
    if not image:
        return {
            "answer": "no_photo",
            "confidence": 0.0,
            "observation": "no photo provided",
            "_flags": [ctx.flag("photo_missing", "warn", "No photo was provided as evidence.", question)],
        }
    path = co.safe_path(image)
    try:
        ans = llm.generate_json(
            f"Look at the photo. Question: {question}\nReturn JSON "
            '{"answer": "yes" | "no" | "unclear", "confidence": 0..1, "observation": "<one sentence of what you see>"}',
            images=[path.read_bytes()],
            purpose="assess_image",
        )
        answer = str(ans.get("answer", "unclear")).lower()
        conf = float(ans.get("confidence") or 0.5)
        obs = ans.get("observation", "")
    except (LLMUnavailable, ValueError):
        answer, conf, obs = "unclear", 0.0, "vision model not available — needs a human look"
    flags = []
    if answer == "unclear" or conf < 0.6:
        flags.append(ctx.flag("photo_unverified", "warn", "The photo could not be assessed confidently.", obs))
    return {
        "answer": answer,
        "confidence": round(conf, 2),
        "observation": obs,
        "_flags": flags,
        "_fields": {
            "Photo check": {"value": f"{answer} — {obs}", "confidence": round(conf, 2), "source": "gemma-vision"}
        },
    }


@action(
    "decide",
    roles=ALL,
    description="Decide the case route from an ordered decision table (first matching row wins). Rows are safe "
    "conditions over fields, metrics, extra context (e.g. a classified reason) and `issues` "
    "(the list of flags raised so far).",
    inputs={"fields": "dict", "metrics": "dict?", "context": "dict?", "table": "list", "default_route": "str"},
    outputs={"route": "str", "reason": "str", "issues": "list"},
)
def decide(
    ctx: ExecContext,
    fields: dict,
    table: list,
    default_route: str,
    metrics: dict | None = None,
    context: dict | None = None,
) -> dict:
    issues = sorted({f["type"] for f in ctx.flags if f.get("severity") in ("warn", "critical")})
    scope = {**(fields or {}), **(metrics or {}), **(context or {}), "issues": issues}
    for row in table or []:
        if expr.evaluate(row["when"], scope):
            return {
                "route": row["route"],
                "reason": row.get("reason", row["when"]),
                "issues": issues,
                "_fields": {"Route": {"value": row["route"], "confidence": 1.0, "source": "rules"}},
            }
    return {
        "route": default_route,
        "reason": "all checks passed",
        "issues": issues,
        "_fields": {"Route": {"value": default_route, "confidence": 1.0, "source": "rules"}},
    }


# ------------------------------------------------------------------------------------ communication & outcomes
LANG = {"en": "English", "hi": "Hindi", "te": "Telugu"}


@action(
    "draft_message",
    roles=ALL,
    description="Write a short, polite message to a person (applicant, customer, candidate, hospital) in their "
    "language, from the facts given. Gemma 4; template fallback offline. Identifiers are masked.",
    inputs={"to_name": "str", "purpose": "str", "facts": "str", "language": "str?"},
    outputs={"subject": "str", "body": "str", "language": "str", "method": "str"},
)
def draft_message(ctx: ExecContext, to_name: str, purpose: str, facts: str, language: str | None = "en") -> dict:
    lang = (language or "en").lower()[:2]
    org = ctx.employee.get("org") or co.company().get("name")
    try:
        masked, mapping = pii.mask(facts or "")
        ans = llm.generate_json(
            f"Write a {purpose} to {to_name} in {LANG.get(lang, 'English')} (native script). Respectful, clear, "
            f"specific about what happens next, under 120 words. Sender: {ctx.employee.get('name')}, {org}.\n"
            f'Facts:\n{masked}\nReturn JSON {{"subject": "...", "body": "..."}}',
            purpose="draft_message",
        )
        ans = pii.unmask(ans, mapping)
        subject, body, method = ans.get("subject", ""), ans.get("body", ""), "gemma"
    except (LLMUnavailable, ValueError):
        subject = purpose[:1].upper() + purpose[1:]
        body = (
            f"Dear {to_name},\n\n{facts}\n\nIf you have any questions, simply reply to this message.\n\n"
            f"Regards,\n{ctx.employee.get('name')}\n{org}"
        )
        method = "template"
    return {
        "subject": subject,
        "body": body,
        "language": lang,
        "method": method,
        "_fields": {"Message": {"value": subject, "confidence": 0.9, "source": method}},
    }


def _out(ctx: ExecContext, kind: str, data: dict) -> dict:
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


@action(
    "send_message",
    roles=ALL,
    side_effect=True,
    description="Send the drafted message (email / SMS / WhatsApp — written to the outbox in this demo).",
    inputs={"to": "str", "subject": "str", "body": "str"},
    outputs={"message_id": "str"},
)
def send_message(ctx: ExecContext, to: str, subject: str, body: str) -> dict:
    return {
        "message_id": _out(
            ctx, "email", {"to": to, "subject": subject, "body": body, "summary": f"Message to {to}: {subject}"}
        )["id"]
    }


@action(
    "record_outcome",
    roles=ALL,
    side_effect=True,
    description="Record the final outcome of the case in the system of record (e.g. 'forwarded to credit officer', "
    "'scholarship recommended', 'onboarding started').",
    inputs={"case_id": "str", "outcome": "str", "summary": "str"},
    outputs={"record_id": "str"},
)
def record_outcome(ctx: ExecContext, case_id: str, outcome: str, summary: str) -> dict:
    return {"record_id": _out(ctx, "decision", {"case_id": case_id, "outcome": outcome, "summary": summary})["id"]}


@action(
    "issue_refund",
    roles=ALL,
    side_effect=True,
    money=True,
    description="Issue a refund to the customer's original payment method.",
    inputs={"reference": "str", "amount": "number", "to": "str"},
    outputs={"refund_id": "str", "amount": "number"},
)
def issue_refund(ctx: ExecContext, reference: str, amount: float, to: str) -> dict:
    doc = _out(
        ctx,
        "payment",
        {
            "reference": reference,
            "amount": amount,
            "to": to,
            "summary": f"Refund {fmt_inr(amount)} to {to} for {reference}",
        },
    )
    return {"refund_id": doc["id"], "amount": amount}


@action(
    "create_request",
    roles=ALL,
    side_effect=True,
    description="Raise an internal request in another team's queue (e.g. IT laptop & email account, payroll setup).",
    inputs={"team": "str", "request": "str"},
    outputs={"request_id": "str"},
)
def create_request(ctx: ExecContext, team: str, request: str) -> dict:
    return {
        "request_id": _out(
            ctx, "request", {"team": team, "request": request, "summary": f"Request to {team}: {request}"}
        )["id"]
    }
