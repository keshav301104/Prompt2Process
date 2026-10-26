"""The workspace lifecycle: first-run status, the optional demo workspace, and reset.

A new workspace starts empty. 'Load demo workspace' only uses the public building blocks — set the
organisation profile, fill the people directory, hire employees from templates — exactly like a customer would.
"""

import subprocess
import sys
from pathlib import Path

import yaml

from . import company as co
from . import config, db, org
from .workforce import compiler, packs

DEMO = Path(__file__).resolve().parent / "seed" / "demo_workspace.yaml"


def status() -> dict:
    o = org.get()
    n = len(db.query("employees"))
    return {
        "org": o,
        "setup_complete": bool(o["name"]) and n > 0,
        "employees": n,
        "templates": len(packs.all_packs()),
        "demo_available": DEMO.exists(),
    }


def ensure_demo_data() -> None:
    """Generate the synthetic demo documents (invoices, cases, ledgers) once."""
    backend = config.ROOT / "backend"
    if not (config.DATA_DIR / "vendors.csv").exists():
        subprocess.run(
            [sys.executable, "-m", "app.seed.generate", "--out", str(config.DATA_DIR)], cwd=backend, check=True
        )
    if not (config.DATA_DIR / "cases").exists():
        subprocess.run([sys.executable, "-m", "app.seed.cases", "--out", str(config.DATA_DIR)], cwd=backend, check=True)
    co.reload()


def load_demo() -> dict:
    ensure_demo_data()
    cfg = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    comp = co.demo_company()
    people = list(cfg.get("people", []))
    for key, role in (("finance_manager", "Finance Manager"), ("cfo", "CFO")):
        if comp.get(key):
            people.append({"key": key, "role": role, **_split(comp[key])})
    org.save({**cfg["org"], "legal_name": comp.get("name", ""), "gstin": comp.get("gstin", ""), "people": people})
    hired = {e.get("template_id") for e in db.query("employees")}
    for member in cfg.get("team", []):
        if member["template"] not in hired:
            compiler.hire_from_template(member["template"], member["name"], reference_only=True)
    db.audit("manager", "demo_loaded", f"demo workspace with {len(cfg.get('team', []))} digital employees")
    return status()


def _split(text: str) -> dict:
    name, _, rest = text.partition("(")
    return {"name": name.strip(), "email": rest.rstrip(")").strip()}


def reset() -> dict:
    with db._lock:
        db._conn.execute("DELETE FROM docs")
        for tbl in ("events", "audit", "corrections", "plan_versions", "settings"):
            db._conn.execute(f"DELETE FROM {tbl}")
        db._conn.commit()
    db.audit("manager", "workspace_reset", "all employees, work and settings cleared")
    return status()
