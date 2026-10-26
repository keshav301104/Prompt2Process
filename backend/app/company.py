"""Loads the workspace's master data files (vendors, purchase orders, goods receipts, posted ledger, AR ledger).

These are the customer's own records (here: the demo workspace's synthetic files). The organisation profile
itself lives in `org.py` (editable in the console), not in code."""

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from . import org
from .config import DATA_DIR


def _csv(name: str) -> list[dict]:
    p = DATA_DIR / name
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _json(name: str, default):
    p = DATA_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("Rs.", "").replace("₹", "").strip())
    except ValueError:
        return None


def norm_name(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"\b(pvt|private|ltd|limited|llp|co|company|and|the|m/s|ms)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def company() -> dict:
    """The organisation profile (from the workspace directory) — never a hardcoded company."""
    return org.scope()


def demo_company() -> dict:
    """The demo workspace's company file, used only by 'Load demo workspace'."""
    return _json("company.json", {})


@lru_cache(maxsize=1)
def vendors() -> list[dict]:
    rows = _csv("vendors.csv")
    for r in rows:
        r["alias_list"] = [a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()]
        r["payment_terms_days"] = int(num(r.get("payment_terms_days")) or 30)
    return rows


def vendor(vendor_id: str | None) -> dict | None:
    return next((v for v in vendors() if v["vendor_id"] == vendor_id), None)


@lru_cache(maxsize=1)
def purchase_orders() -> dict[str, dict]:
    return {po["po_number"]: po for po in _json("purchase_orders.json", [])}


@lru_cache(maxsize=1)
def grns_by_po() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for g in _json("grns.json", []):
        out.setdefault(g["po_number"], []).append(g)
    return out


@lru_cache(maxsize=1)
def posted_invoices() -> list[dict]:
    rows = _csv("posted_invoices.csv")
    for r in rows:
        r["total"] = num(r.get("total")) or 0.0
    return rows


def ledger(name: str) -> list[dict]:
    """Rows of any ledger file in the workspace (an intake channel of type 'ledger')."""
    return _csv(name)


@lru_cache(maxsize=1)
def ar_ledger() -> list[dict]:
    rows = _csv("ar_ledger.csv")
    for r in rows:
        for k in (
            "amount",
            "days_overdue",
            "avg_delay_days_history",
            "broken_promises",
            "last_reminder_level",
            "customer_since_months",
        ):
            if k in r:
                r[k] = num(r[k]) or 0
    return rows


@lru_cache(maxsize=1)
def ar_history() -> list[dict]:
    rows = _csv("ar_history.csv")
    return [{k: num(v) for k, v in r.items()} for r in rows]


def sops() -> list[dict]:
    out = []
    folder = DATA_DIR / "sops"
    for p in sorted(folder.glob("*.md")) if folder.exists() else []:
        text = p.read_text(encoding="utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), p.stem)
        out.append({"id": p.stem, "title": title, "filename": p.name, "text": text})
    return out


def reload() -> None:
    for fn in (vendors, purchase_orders, grns_by_po, posted_invoices, ar_ledger, ar_history):
        fn.cache_clear()


def safe_path(rel: str) -> Path:
    """Resolve a file path and refuse anything outside the company data folder (sandbox)."""
    p = (DATA_DIR / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    if DATA_DIR not in p.parents and p != DATA_DIR:
        from .core.registry import PolicyError

        raise PolicyError(f"path '{rel}' is outside the sandbox folder")
    return p
