"""Reading invoices: text layer first (fast, free), Gemma 4 for anything the fast path can't read,
Gemma 4 vision for scanned images. Every field carries a confidence and the source that produced it."""

import re
from datetime import datetime

import pymupdf

from .. import company as co
from ..config import STATE_DIR
from ..core.registry import ExecContext, TransientError, action
from ..llm.gemma import LLMUnavailable, llm
from ..safety import injection, pii

KEY_FIELDS = ("vendor_name", "vendor_gstin", "invoice_no", "total")
RENDER_DIR = STATE_DIR / "renders"
RENDER_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------------------------ read_invoice
@action(
    "read_invoice",
    roles=("ap",),
    description="Open an invoice file from the inbox (PDF). Returns its text layer, renders scans to an image, "
    "and screens the content for hidden instructions (prompt injection).",
    inputs={"file": "str"},
    outputs={
        "text": "str",
        "has_text_layer": "bool",
        "pages": "number",
        "image_path": "str",
        "injection_detected": "bool",
        "injection_score": "number",
    },
)
def read_invoice(ctx: ExecContext, file: str) -> dict:
    path = co.safe_path(file)
    doc = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in doc)
    has_text = len(text.strip()) > 60
    image_path = ""
    if not has_text:
        pix = doc[0].get_pixmap(dpi=110)
        out = RENDER_DIR / f"{path.stem}.png"
        pix.save(out)
        image_path = str(out)
    pages = doc.page_count
    doc.close()

    scan = injection.scan(text)
    flags = []
    if scan["detected"]:
        ev = scan["hits"][0]["snippet"] if scan["hits"] else ""
        flags.append(
            ctx.flag(
                "injection",
                "critical",
                "Instruction-like text found inside the document. Treated as data, not obeyed.",
                ev,
            )
        )
    return {
        "text": text,
        "has_text_layer": has_text,
        "pages": pages,
        "image_path": image_path,
        "injection_detected": scan["detected"],
        "injection_score": scan["score"],
        "_flags": flags,
    }


# ------------------------------------------------------------------------------------ template parser
def _date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _grab(pattern: str, text: str, flags=re.MULTILINE | re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


ROW_RE = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s+(\d{4,8})\s+([\d,]+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$")


def parse_template(text: str) -> dict:
    lines = [ln.rstrip() for ln in text.splitlines()]
    vendor_name = None
    for i, ln in enumerate(lines):
        if ln.strip().upper() == "TAX INVOICE":
            vendor_name = next((x.strip() for x in lines[i + 1 :] if x.strip()), None)
            break
    rows = []
    # rows may come as one line, or as a run of consecutive short lines; try joined windows too
    stripped = [ln.strip() for ln in lines if ln.strip()]
    for ln in stripped:
        m = ROW_RE.match(ln)
        if m:
            rows.append(m)
    if not rows:
        for size in (6, 5):
            for i in range(len(stripped) - size + 1):
                m = ROW_RE.match("  ".join(stripped[i : i + size]))
                if m and stripped[i].isdigit():
                    rows.append(m)
    items = [
        {
            "description": m.group(2).strip(),
            "hsn": m.group(3),
            "qty": co.num(m.group(4)),
            "rate": co.num(m.group(5)),
            "amount": co.num(m.group(6)),
        }
        for m in rows
    ]

    def money(label):
        return co.num(_grab(rf"^\s*{label}\s*(?:@\s*[\d.]+\s*%)?\s*:?\s*(?:Rs\.?|₹)?\s*([\d,]+\.\d{{2}})", text))

    def rate(label):
        r = _grab(rf"^\s*{label}\s*@\s*([\d.]+)\s*%", text)
        return co.num(r)

    po = _grab(r"^\s*PO Number\s*:\s*(\S+)", text)
    bank = re.search(
        r"Bank A/c\s*:?\s*([0-9]{6,20})\s*(?:\S*\s*)?IFSC\s*:?\s*([A-Z]{4}0[A-Z0-9]{6})", text, re.IGNORECASE
    )
    out = {
        "vendor_name": vendor_name,
        "vendor_gstin": _grab(r"^\s*GSTIN\s*:\s*([0-9A-Z]{15})\b", text),
        "buyer_gstin": _grab(r"^\s*Buyer GSTIN\s*:\s*([0-9A-Z]{15})\b", text),
        "invoice_no": _grab(r"^\s*Invoice No\.?\s*:\s*(\S+)", text),
        "invoice_date": _date(_grab(r"^\s*Invoice Date\s*:\s*(\S+)", text)),
        "due_date": _date(_grab(r"^\s*Due Date\s*:\s*(\S+)", text)),
        "po_number": None if (po or "").upper() in ("N/A", "NA", "-", "") else po,
        "line_items": items,
        "subtotal": money("Subtotal"),
        "cgst": money("CGST"),
        "sgst": money("SGST"),
        "igst": money("IGST"),
        "cgst_rate": rate("CGST"),
        "sgst_rate": rate("SGST"),
        "igst_rate": rate("IGST"),
        "total": money(r"(?:Grand\s+)?Total"),
        "bank_account": bank.group(1) if bank else None,
        "ifsc": bank.group(2) if bank else None,
        "notes": _grab(r"^\s*Notes\s*:\s*(.+)$", text),
    }
    return out


# ------------------------------------------------------------------------------------ Gemma extraction
EXTRACT_PROMPT = """You are an accounts-payable document reader for an Indian company.
Extract the invoice fields as JSON with exactly these keys:
vendor_name, vendor_gstin, buyer_gstin, invoice_no, invoice_date (YYYY-MM-DD), due_date (YYYY-MM-DD), po_number (null if N/A),
line_items (list of {{description, hsn, qty, rate, amount}}), subtotal, cgst, sgst, igst, cgst_rate, sgst_rate, igst_rate, total,
bank_account, ifsc, notes,
confidence (object mapping each of vendor_name, vendor_gstin, invoice_no, invoice_date, total to a number 0..1 = how sure you are it is read correctly).
Numbers must be plain numbers without commas. Use null for anything not present. Copy identifiers exactly, character by character.
{doc}"""


def _gemma_extract(text: str | None, image_path: str | None) -> dict:
    if image_path:
        with open(image_path, "rb") as f:
            img = f.read()
        data = llm.generate_json(
            EXTRACT_PROMPT.format(doc="Read the attached scanned invoice image."),
            images=[img],
            purpose="extract_invoice:vision",
        )
        data["_source"] = "gemma-vision"
        return data
    masked, mapping = pii.mask(text or "", keep=("GSTIN",))  # GSTIN is needed for checks; other IDs are masked
    data = llm.generate_json(EXTRACT_PROMPT.format(doc=injection.wrap_document(masked)), purpose="extract_invoice")
    data = pii.unmask(data, mapping)
    data["_source"] = "gemma"
    data["_masked"] = pii.summary(mapping)
    return data


def _consistent(d: dict) -> bool:
    items = d.get("line_items") or []
    sub, tot = co.num(d.get("subtotal")), co.num(d.get("total"))
    if not items or sub is None or tot is None:
        return False
    s = sum(co.num(i.get("amount")) or 0 for i in items)
    tax = sum(co.num(d.get(k)) or 0 for k in ("cgst", "sgst", "igst"))
    return abs(s - sub) <= 1.0 and abs(sub + tax - tot) <= 1.0


@action(
    "extract_invoice",
    roles=("ap",),
    description="Extract structured invoice fields (vendor, GSTIN, invoice no, dates, PO, line items, taxes, total, "
    "bank details) with a confidence score per field. Uses the text layer when possible, Gemma 4 for "
    "unusual layouts and Gemma 4 vision for scans. Personal identifiers are masked before any model call.",
    inputs={"document": "dict"},
    outputs={
        "vendor_name": "str",
        "vendor_gstin": "str",
        "buyer_gstin": "str",
        "invoice_no": "str",
        "invoice_date": "date",
        "due_date": "date",
        "po_number": "str",
        "line_items": "list",
        "subtotal": "number",
        "cgst": "number",
        "sgst": "number",
        "igst": "number",
        "tax_total": "number",
        "total": "number",
        "bank_account": "str",
        "ifsc": "str",
        "notes": "str",
        "method": "str",
        "min_confidence": "number",
        "low_confidence": "bool",
    },
)
def extract_invoice(ctx: ExecContext, document: dict) -> dict:
    document = document or {}
    text, image_path = document.get("text") or "", document.get("image_path") or ""
    mode = ctx.settings.get("extraction_mode", "template_first")
    data, source, conf = {}, "template", {}

    if document.get("has_text_layer") and mode == "template_first":
        data = parse_template(text)
        if all(data.get(k) for k in KEY_FIELDS) and data["line_items"]:
            conf = dict.fromkeys(data, 0.98)
        else:
            data = {}
    if not data:
        try:
            data = _gemma_extract(
                text if document.get("has_text_layer") else None, None if document.get("has_text_layer") else image_path
            )
            source = data.pop("_source", "gemma")
            conf = {k: float(v) for k, v in (data.pop("confidence", None) or {}).items() if isinstance(v, (int, float))}
        except LLMUnavailable:
            if document.get("has_text_layer"):
                data, source = parse_template(text), "template"
                conf = {k: (0.9 if data.get(k) else 0.0) for k in data}
            else:
                data, source = {}, "unreadable"
        except ValueError as e:
            raise TransientError(f"model returned unreadable JSON: {e}") from e

    for k in ("subtotal", "cgst", "sgst", "igst", "total", "cgst_rate", "sgst_rate", "igst_rate"):
        data[k] = co.num(data.get(k))
    data["line_items"] = [
        {
            "description": i.get("description"),
            "hsn": str(i.get("hsn") or ""),
            "qty": co.num(i.get("qty")),
            "rate": co.num(i.get("rate")),
            "amount": co.num(i.get("amount")),
        }
        for i in (data.get("line_items") or [])
        if isinstance(i, dict)
    ]
    data["tax_total"] = round(sum(data.get(k) or 0 for k in ("cgst", "sgst", "igst")), 2)
    if data.get("po_number") in ("N/A", "NA", "null", ""):
        data["po_number"] = None

    # confidence: model's own estimate, cross-checked against the invoice's arithmetic
    consistent = _consistent(data)
    base = 0.98 if source == "template" else (0.9 if source == "gemma" else 0.8)
    field_conf = {}
    for k in (*KEY_FIELDS, "invoice_date", "due_date", "po_number", "subtotal", "tax_total"):
        c = conf.get(k, base if data.get(k) is not None else 0.0)
        if source != "template":
            c = min(c, 0.97) if consistent else min(c, 0.6)
        if data.get(k) is None and k in KEY_FIELDS:
            c = 0.0
        field_conf[k] = round(float(c), 2)
    min_conf = min(field_conf[k] for k in KEY_FIELDS)
    low = min_conf < 0.8

    flags = []
    if low:
        weak = [k for k in KEY_FIELDS if field_conf[k] < 0.8]
        flags.append(
            ctx.flag(
                "low_confidence",
                "warn",
                f"Could not read {', '.join(weak)} with enough confidence ({source}).",
                f"min confidence {min_conf:.2f}",
            )
        )
    fields = {
        k: {"value": data.get(k), "confidence": field_conf.get(k, base), "source": source}
        for k in (
            "vendor_name",
            "vendor_gstin",
            "invoice_no",
            "invoice_date",
            "due_date",
            "po_number",
            "subtotal",
            "tax_total",
            "total",
        )
    }
    fields["line_items"] = {"value": data["line_items"], "confidence": base, "source": source}

    out = {
        k: data.get(k)
        for k in (
            "vendor_name",
            "vendor_gstin",
            "buyer_gstin",
            "invoice_no",
            "invoice_date",
            "due_date",
            "po_number",
            "line_items",
            "subtotal",
            "cgst",
            "sgst",
            "igst",
            "cgst_rate",
            "sgst_rate",
            "igst_rate",
            "tax_total",
            "total",
            "bank_account",
            "ifsc",
            "notes",
        )
    }
    out.update(
        {
            "method": source,
            "min_confidence": min_conf,
            "low_confidence": low,
            "consistent": consistent,
            "_flags": flags,
            "_fields": fields,
        }
    )
    return out
