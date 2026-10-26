"""Prompt2Process API — FastAPI app. Run from backend/:  uvicorn app.main:app --reload --port 8000"""

import re
from collections import Counter
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    actions,  # noqa: F401  (registers tools)
    config,
    db,
    org,
    workspace,
)
from . import company as co
from .core import checker
from .core.registry import catalog
from .learning import classifier
from .llm.gemma import llm
from .workforce import backtest, compiler, employees, packs, work

app = FastAPI(title="Prompt2Process — AI back-office workforce", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    # Nothing is seeded: a new workspace starts empty (onboarding or "Load demo workspace").
    # Tasks that were mid-run when the server stopped are re-queued; LangGraph checkpoints let them continue.
    for t in db.query("tasks", status="running", limit=500):
        db.update("tasks", t["id"], status="queued")


# ------------------------------------------------------------------------------------ roles & permissions
ROLES: dict[str, dict[str, Any]] = {
    "owner": {"label": "Owner", "can": {"*"}, "about": "Sees every department; can do everything."},
    "manager": {
        "label": "Department manager",
        "can": {
            "work.run",
            "inbox.decide",
            "employee.promote",
            "settings.edit",
            "learning.train",
            "task.correct",
            "backtest.run",
        },
        "about": "Runs the team: work queues, approvals, promotions.",
    },
    "designer": {
        "label": "Process designer",
        "can": {"hire", "plan.edit", "plan.check", "backtest.run", "learning.train"},
        "about": "Hires from SOPs, edits workflows, runs backtests.",
    },
    "reviewer": {
        "label": "Reviewer",
        "can": {"inbox.decide", "task.correct"},
        "about": "Works the review inbox and corrects the AI.",
    },
    "auditor": {"label": "Auditor", "can": set(), "about": "Read-only: audit trail and evidence."},
}
GUARDS = [
    ("POST", r"^/api/employees/[^/]+/promote$", "employee.promote"),
    ("PUT", r"^/api/employees/[^/]+/plan$", "plan.edit"),
    ("POST", r"^/api/employees/[^/]+/plan/check$", "plan.check"),
    ("POST", r"^/api/hire/", "hire"),
    ("POST", r"^/api/employees/[^/]+/(ingest|run|upload)$", "work.run"),
    ("POST", r"^/api/tasks/[^/]+/correct$", "task.correct"),
    ("POST", r"^/api/inbox/[^/]+/decide$", "inbox.decide"),
    ("POST", r"^/api/learning/[^/]+/train$", "learning.train"),
    ("POST", r"^/api/employees/[^/]+/backtest$", "backtest.run"),
    ("PUT", r"^/api/settings$", "settings.edit"),
    ("PUT", r"^/api/org$", "settings.edit"),
    ("POST", r"^/api/workspace/(demo|reset)$", "admin"),
]


def current_role(request: Request) -> str:
    r = (request.headers.get("x-p2p-role") or "owner").lower()
    return r if r in ROLES else "owner"


@app.middleware("http")
async def permissions(request: Request, call_next):
    role = current_role(request)
    can = ROLES[role]["can"]
    for method, pattern, perm in GUARDS:
        if request.method == method and re.match(pattern, request.url.path):
            if "*" not in can and perm not in can:
                return JSONResponse(
                    {"detail": f"The {ROLES[role]['label']} role cannot do this ({perm})."}, status_code=403
                )
    return await call_next(request)


@app.get("/api/roles")
def roles():
    return [{"id": k, "label": v["label"], "about": v["about"], "can": sorted(v["can"])} for k, v in ROLES.items()]


@app.get("/api/packs")
def list_packs():
    """The template library."""
    counts = Counter(e.get("template_id") for e in db.query("employees"))
    return [packs.summary(p) | {"hired_count": counts.get(p["id"], 0)} for p in packs.all_packs()]


# ------------------------------------------------------------------------------------ workspace & organisation
@app.get("/api/workspace")
def get_workspace():
    return workspace.status()


@app.post("/api/workspace/demo")
def load_demo():
    return workspace.load_demo()


@app.post("/api/workspace/reset")
def reset_workspace():
    return workspace.reset()


@app.get("/api/org")
def get_org():
    return org.get()


@app.put("/api/org")
def put_org(body: dict):
    return org.save(body)


# ------------------------------------------------------------------------------------ helpers
def _emp(emp_id: str) -> dict:
    e = db.get("employees", emp_id)
    if not e:
        raise HTTPException(404, "employee not found")
    return e


def _task_view(t: dict) -> dict:
    out = {k: v for k, v in t.items() if k not in ("plan", "ref")}
    out.setdefault("outcome", {})
    return out


# ------------------------------------------------------------------------------------ system
@app.get("/api/health")
def health():
    s = work.settings()
    return {
        "status": "ok",
        "llm_mode": llm.mode,
        "model": llm.model or "—",
        "vision_model": llm.vision_model or "—",
        "llm_error": llm.error,
        "chaos_mode": s["chaos_mode"],
    }


@app.get("/api/settings")
def get_settings():
    return work.settings() | {"llm_mode": llm.mode}


@app.put("/api/settings")
def put_settings(body: dict):
    allowed = set(config.DEFAULT_SETTINGS)
    db.set_settings({k: v for k, v in body.items() if k in allowed})
    db.audit("manager", "settings", ", ".join(f"{k}={v}" for k, v in body.items() if k in allowed))
    return get_settings()


@app.get("/api/llm/trace")
def llm_trace():
    return {"mode": llm.mode, "model": llm.model, "total_calls": llm.total_calls, "calls": list(llm.trace)}


@app.get("/api/llm/models")
def llm_models():
    return {"models": llm.list_models(), "selected": llm.model}


@app.get("/api/tools")
def tools():
    return catalog()


@app.get("/api/company")
def company_info():
    return {
        "company": org.get(),
        "vendors": len(co.vendors()),
        "purchase_orders": len(co.purchase_orders()),
        "posted_invoices": len(co.posted_invoices()),
    }


# ------------------------------------------------------------------------------------ overview
@app.get("/api/overview")
def overview():
    s = work.settings()
    emps = db.query("employees")
    tasks = [t for t in db.query("tasks", limit=5000) if t.get("mode") != "shadow"]
    views = [employees.view(e, s) for e in emps]
    outcomes = Counter((t.get("outcome") or {}).get("final_decision") or t["status"] for t in tasks)
    flags = Counter(f["type"] for t in tasks for f in t.get("flags", []))
    finished = sorted(
        [t for t in tasks if t["status"] in ("done", "rejected", "needs_review", "failed")],
        key=lambda t: t["updated_at"],
    )
    series = [
        {"task_index": i + 1, "ai_calls": int(t.get("ai_calls") or 0), "employee_id": t["employee_id"]}
        for i, t in enumerate(finished)
    ]
    activity = db.events(limit=30)
    return {
        "employees": len(emps),
        "tasks_done": sum(v["kpis"]["tasks_done"] for v in views),
        "hours_saved": round(sum(v["kpis"]["hours_saved"] for v in views), 1),
        "money_saved_inr": sum(v["kpis"]["money_saved_inr"] for v in views),
        "ai_calls_total": sum(v["kpis"]["ai_calls_total"] for v in views),
        "open_inbox": len(db.query("inbox", status="open")),
        "outcomes": dict(outcomes),
        "flags_by_type": dict(flags),
        "ai_calls_series": series,
        "activity": activity,
    }


# ------------------------------------------------------------------------------------ employees
@app.get("/api/employees")
def list_employees():
    s = work.settings()
    return [employees.view(e, s) for e in sorted(db.query("employees"), key=lambda e: e["created_at"])]


@app.get("/api/employees/{emp_id}")
def get_employee(emp_id: str):
    return employees.view(_emp(emp_id), work.settings())


class PromoteBody(BaseModel):
    level: int


@app.post("/api/employees/{emp_id}/promote")
def promote(emp_id: str, body: PromoteBody):
    emp = _emp(emp_id)
    cur = int(emp.get("autonomy_level", 0))
    if body.level not in (0, 1, 2):
        raise HTTPException(400, "level must be 0, 1 or 2")
    if body.level > cur:
        p = employees.promotion(emp)
        if body.level != cur + 1 or not p["eligible"]:
            raise HTTPException(400, f"Not eligible: {p['reason']}")
    emp["autonomy_level"] = body.level
    db.put("employees", emp)
    db.audit(
        "manager",
        "promoted" if body.level > cur else "demoted",
        f"{emp['name']}: {employees.LEVELS[cur]} → {employees.LEVELS[body.level]}",
    )
    return employees.view(emp, work.settings())


class PlanBody(BaseModel):
    plan: dict
    note: str | None = None


@app.put("/api/employees/{emp_id}/plan")
def put_plan(emp_id: str, body: PlanBody):
    emp, report = employees.save_plan(_emp(emp_id), body.plan, body.note or "edited in console")
    return {"employee": employees.view(emp, work.settings()), "check": report}


@app.post("/api/employees/{emp_id}/plan/check")
def check_plan(emp_id: str, body: PlanBody):
    emp = _emp(emp_id)
    report, _ = checker.check(body.plan, emp["role"], emp.get("tools"))
    return report


@app.get("/api/employees/{emp_id}/versions")
def versions(emp_id: str):
    return [{k: v[k] for k in ("version", "created_at", "note")} for v in db.plan_versions(emp_id)]


@app.get("/api/employees/{emp_id}/diff")
def diff(emp_id: str, a: int, b: int):
    vs = {v["version"]: v["plan"] for v in db.plan_versions(emp_id)}
    if a not in vs or b not in vs:
        raise HTTPException(404, "version not found")
    return {"changes": employees.diff(vs[a], vs[b])}


# ------------------------------------------------------------------------------------ hiring
@app.get("/api/sops")
def sops():
    """Template SOPs plus any sample SOP documents in the workspace (for the 'upload your own SOP' flow)."""
    out = [
        {
            "id": p["id"],
            "template_id": p["id"],
            "title": packs.sop_title(p),
            "filename": f"{p['id']}_sop.md",
            "text": p["sop"],
            "sector": p["sector"],
            "suggested_name": p["employee"]["name"],
        }
        for p in packs.all_packs()
    ]
    out += [s | {"template_id": None, "sector": "Sample document"} for s in co.sops()]
    return out


class DraftBody(BaseModel):
    name: str = ""
    template_id: str | None = None
    sop_text: str | None = None


@app.post("/api/hire/draft")
def hire_draft(body: DraftBody):
    try:
        return compiler.draft(body.name, body.template_id, body.sop_text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/hire/draft-upload")
async def hire_draft_upload(file: UploadFile = File(...), name: str = Form(""), template_id: str | None = Form(None)):
    data = await file.read()
    if file.filename and file.filename.lower().endswith(".pdf"):
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(p.get_text() for p in doc)
    else:
        text = data.decode("utf-8", errors="ignore")
    try:
        return compiler.draft(name, template_id, text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class CompileBody(BaseModel):
    draft_id: str
    answers: dict = {}


@app.post("/api/hire/compile")
def hire_compile(body: CompileBody):
    try:
        return compiler.compile_plan(body.draft_id, body.answers)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class ConfirmBody(BaseModel):
    draft_id: str
    name: str | None = None


@app.post("/api/hire/confirm")
def hire_confirm(body: ConfirmBody):
    try:
        emp = compiler.confirm(body.draft_id, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return employees.view(emp, work.settings())


# ------------------------------------------------------------------------------------ work
@app.post("/api/employees/{emp_id}/ingest")
def ingest(emp_id: str):
    return {"created": [_task_view(t) for t in work.ingest(_emp(emp_id))]}


@app.post("/api/employees/{emp_id}/upload")
async def upload(emp_id: str, file: UploadFile = File(...)):
    t = work.add_upload(_emp(emp_id), file.filename or "upload.pdf", await file.read())
    return _task_view(t)


class RunBody(BaseModel):
    task_ids: list[str] | None = None


@app.post("/api/employees/{emp_id}/run")
def run(emp_id: str, body: RunBody | None = None):
    _emp(emp_id)
    return {"started": work.run_queue(emp_id, body.task_ids if body else None)}


@app.get("/api/tasks")
def tasks(employee_id: str | None = None, status: str | None = None):
    return [_task_view(t) for t in db.query("tasks", employee_id=employee_id, status=status, limit=500)]


@app.get("/api/tasks/{task_id}")
def task(task_id: str):
    t = db.get("tasks", task_id)
    if not t:
        raise HTTPException(404, "task not found")
    return _task_view(t)


@app.get("/api/tasks/{task_id}/events")
def task_events(task_id: str):
    return db.events(task_id)


@app.get("/api/tasks/{task_id}/document")
def task_document(task_id: str):
    t = db.get("tasks", task_id)
    if not t or not t.get("file"):
        raise HTTPException(404, "no document")
    path = co.safe_path(t["file"])
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.get("/api/tasks/{task_id}/file")
def task_file(task_id: str, path: str):
    t = db.get("tasks", task_id)
    if not t or path not in (t.get("files") or [t.get("file")]):
        raise HTTPException(404, "file not part of this task")
    p = co.safe_path(path)
    media = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png" if p.suffix.lower() == ".png" else None
    return FileResponse(p, media_type=media, headers={"Content-Disposition": "inline"})


@app.get("/api/tasks/{task_id}/outputs")
def task_outputs(task_id: str):
    return [o for o in db.query("outputs", limit=2000) if o.get("task_id") == task_id]


class CorrectBody(BaseModel):
    field: str
    value: str | float | int | None


@app.post("/api/tasks/{task_id}/correct")
def correct(task_id: str, body: CorrectBody):
    if not db.get("tasks", task_id):
        raise HTTPException(404, "task not found")
    n = work.correct(task_id, body.field, body.value)
    return {"ok": True, "n_corrections": n}


# ------------------------------------------------------------------------------------ inbox
@app.get("/api/inbox")
def inbox(status: str | None = "open"):
    items = db.query("inbox", status=status or None, limit=500)
    for i in items:
        if i["kind"] == "review" and i.get("task_id"):
            t = db.get("tasks", i["task_id"]) or {}
            i["payload"]["fields"] = t.get("fields")
            i["payload"]["flags"] = t.get("flags") or i["payload"].get("flags")
    return items


class DecideBody(BaseModel):
    decision: str
    note: str | None = None
    edits: dict | None = None


@app.post("/api/inbox/{item_id}/decide")
def decide(item_id: str, body: DecideBody, request: Request):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    try:
        return work.decide(
            item_id, body.decision, body.note or "", body.edits, by=ROLES[current_role(request)]["label"]
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------------------------ learning
@app.get("/api/learning/{emp_id}")
def learning(emp_id: str):
    _emp(emp_id)
    return classifier.status(emp_id)


@app.post("/api/learning/{emp_id}/train")
def train(emp_id: str):
    _emp(emp_id)
    return classifier.train(emp_id)


# ------------------------------------------------------------------------------------ backtests
@app.post("/api/employees/{emp_id}/backtest")
def start_backtest(emp_id: str):
    return {"backtest_id": backtest.start(_emp(emp_id))}


@app.get("/api/backtests/{bt_id}")
def get_backtest(bt_id: str):
    b = db.get("backtests", bt_id)
    if not b:
        raise HTTPException(404, "backtest not found")
    return b


@app.get("/api/employees/{emp_id}/backtests")
def list_backtests(emp_id: str):
    return [backtest.summary(b, with_rows=False) for b in db.query("backtests", employee_id=emp_id, limit=50)]


# ------------------------------------------------------------------------------------ audit / outputs
@app.get("/api/audit")
def audit(limit: int = 100):
    return db.audit_log(limit)


@app.get("/api/outputs")
def outputs(kind: str | None = None, limit: int = 200):
    return db.query("outputs", status=kind, limit=limit)


# ------------------------------------------------------------------------------------ frontend
if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse(
            {
                "prompt2process": "API running. Build the frontend (cd frontend && npm run build) to serve the console here."
            }
        )
