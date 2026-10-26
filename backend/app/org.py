"""The workspace's organisation profile and people directory.

Nothing about the customer is hardcoded: the company profile and the people who approve things
(Finance Manager, CFO, Branch Manager, …) live here, are edited in the console, and are referenced by
plans as `$org.people.<key>` — so approvals always route to whoever is in the directory today.
"""

import re

from . import db

_DOC = ("org", "default")
EMPTY = {
    "id": "default",
    "name": "",
    "legal_name": "",
    "industry": "",
    "city": "",
    "state_code": "",
    "gstin": "",
    "currency": "INR",
    "people": [],
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def get() -> dict:
    doc = db.get(*_DOC)
    return {**EMPTY, **(doc or {})}


def save(data: dict) -> dict:
    cur = get()
    for k in ("name", "legal_name", "industry", "city", "state_code", "gstin", "currency"):
        if k in data and data[k] is not None:
            cur[k] = str(data[k]).strip()
    if "people" in data:
        cur["people"] = [_person(p) for p in data["people"] or [] if (p.get("role") or p.get("key"))]
    db.put("org", cur)
    db.audit("manager", "org_updated", f"{cur['name'] or 'workspace'}: {len(cur['people'])} people in directory")
    return cur


def _person(p: dict) -> dict:
    role = (p.get("role") or p.get("key") or "").strip()
    return {
        "role": role,
        "key": p.get("key") or slug(role),
        "name": (p.get("name") or "").strip(),
        "email": (p.get("email") or "").strip(),
    }


def set_person(key: str, role: str, value: str) -> None:
    """Store an answer like 'Ravi Teja (ravi@x.in)' for a directory role."""
    m = re.match(r"^\s*(.*?)\s*[(<]\s*([^)>]+@[^)>]+)\s*[)>]\s*$", value or "")
    name, email = (m.group(1), m.group(2)) if m else (value.strip(), "")
    org = get()
    people = [p for p in org["people"] if p["key"] != key]
    people.append({"role": role, "key": key, "name": name, "email": email})
    save({"people": people})


def person(key: str) -> str | None:
    p = next((p for p in get()["people"] if p["key"] == key), None)
    if not p:
        return None
    return f"{p['name']} ({p['email']})" if p.get("email") else p["name"]


def scope() -> dict:
    """What plans can reference as $org.*"""
    o = get()
    return {
        **{k: o[k] for k in ("name", "legal_name", "industry", "city", "state_code", "gstin", "currency")},
        "people": {p["key"]: (f"{p['name']} ({p['email']})" if p.get("email") else p["name"]) for p in o["people"]},
    }


def is_set_up() -> bool:
    return bool(get()["name"])
