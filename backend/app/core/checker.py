"""The plan checker — Prompt2Process's "type checker" for business workflows.

Runs 8 checks before anything executes. Errors are precise ("[s8] ...") so they can be fed back to the
model for automatic repair, and shown to the manager.
"""
import difflib
import re

from pydantic import ValidationError

from . import expr
from .registry import REGISTRY
from .schema import Plan

ALLOWED_FALLBACKS = {None, "escalate_to_human", "skip"}
SCOPE_FIELDS = {
    "task": {"file": "str", "id": "str", "title": "str", "customer_id": "str", "case_id": "str", "files": "list"},
    "company": {"name": "str", "gstin": "str", "state_code": "str", "city": "str", "finance_manager": "str",
                "cfo": "str", "sales_manager": "str"},
    "employee": {"name": "str", "id": "str"},
}
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_STEPS = 40


def _compatible(have: str, want: str) -> bool:
    have, want = have.rstrip("?"), want.rstrip("?")
    if "any" in (have, want) or have == want:
        return True
    if want == "str" and have in ("date", "number"):
        return True
    if want == "date" and have == "str":
        return True
    return False


def _literal_type_ok(value, want: str) -> bool:
    want = want.rstrip("?")
    if value is None:
        return True
    return {
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "bool": isinstance(value, bool),
        "list": isinstance(value, list),
        "dict": isinstance(value, dict),
        "str": isinstance(value, str),
        "date": isinstance(value, str),
    }.get(want, True)


def check(plan_raw, role: str, tools: list[str] | None = None) -> tuple[dict, dict | None]:
    """Returns (CheckReport, normalised_plan_or_None)."""
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add(cid: str, name: str, details: list[str], warn: list[str] | None = None) -> None:
        checks.append({"id": cid, "name": name, "passed": not details, "details": details + (warn or [])})
        errors.extend(details)
        warnings.extend(warn or [])

    # 1. structure
    try:
        plan = Plan.model_validate(plan_raw if isinstance(plan_raw, dict) else plan_raw.model_dump())
    except ValidationError as e:
        msgs = [f"plan format: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:8]]
        add("structure", "Plan structure", msgs)
        for cid, name in [("ids", "Unique step IDs"), ("actions", "Known actions"), ("privilege", "Least privilege"),
                          ("params", "Parameters"), ("refs", "References & types"), ("conditions", "Conditions"),
                          ("policy", "Company policy")]:
            checks.append({"id": cid, "name": name, "passed": False, "details": ["not run (plan structure invalid)"]})
        return {"ok": False, "checks": checks, "errors": errors, "warnings": warnings}, None
    det = []
    if not plan.steps:
        det.append("plan has no steps")
    if len(plan.steps) > MAX_STEPS:
        det.append(f"plan has {len(plan.steps)} steps; the limit is {MAX_STEPS}")
    add("structure", "Plan structure", det)

    # 2. ids
    det, seen = [], set()
    for s in plan.steps:
        if not ID_RE.match(s.id):
            det.append(f"[{s.id}] step id must be a simple name like s1")
        if s.id in seen:
            det.append(f"[{s.id}] duplicate step id")
        if s.id in SCOPE_FIELDS:
            det.append(f"[{s.id}] '{s.id}' is reserved")
        seen.add(s.id)
    add("ids", "Unique step IDs", det)

    # 3. actions exist
    det = []
    for s in plan.steps:
        if s.action not in REGISTRY:
            near = difflib.get_close_matches(s.action, REGISTRY.keys(), n=1)
            det.append(f"[{s.id}] unknown action '{s.action}'" + (f" — did you mean '{near[0]}'?" if near else
                                                                    f" — allowed: {', '.join(sorted(REGISTRY))}"))
        else:
            s.side_effect = REGISTRY[s.action].side_effect
    add("actions", "Known actions", det)

    # 4. least privilege
    det = []
    for s in plan.steps:
        spec = REGISTRY.get(s.action)
        if spec and not spec.allowed(role):
            det.append(f"[{s.id}] '{s.action}' is not permitted for the {role} role")
        if spec and tools is not None and s.action not in tools:
            det.append(f"[{s.id}] '{s.action}' is not in this employee's granted tools")
    add("privilege", "Least privilege", det)

    # 5. params
    det = []
    for s in plan.steps:
        spec = REGISTRY.get(s.action)
        if not spec:
            continue
        missing = spec.required() - set(s.params)
        if missing:
            det.append(f"[{s.id}] {s.action} is missing required parameter(s): {', '.join(sorted(missing))}")
        unknown = set(s.params) - set(spec.inputs)
        if unknown:
            det.append(f"[{s.id}] {s.action} has no parameter(s) {', '.join(sorted(unknown))}; "
                       f"it accepts: {', '.join(spec.inputs)}")
        for k, v in s.params.items():
            if k in spec.inputs and not expr.value_refs(v) and not _literal_type_ok(v, spec.inputs[k]):
                det.append(f"[{s.id}] parameter '{k}' must be {spec.inputs[k].rstrip('?')}, got {type(v).__name__}")
    add("params", "Parameters", det)

    # 6. references + types
    det, warn = [], []
    index = {s.id: i for i, s in enumerate(plan.steps)}

    def check_path(s_idx: int, sid: str, path: list[str], where: str, want: str | None = None) -> None:
        root = path[0]
        if root in SCOPE_FIELDS:
            if len(path) > 1 and path[1] not in SCOPE_FIELDS[root]:
                warn.append(f"[{sid}] {where}: '{root}.{path[1]}' is not a known {root} field")
            return
        if root not in index:
            det.append(f"[{sid}] {where}: '{'.'.join(path)}' refers to unknown step '{root}'")
            return
        if index[root] >= s_idx:
            det.append(f"[{sid}] {where}: uses '{root}' which has not run yet (steps run top to bottom)")
            return
        src = REGISTRY.get(plan.steps[index[root]].action)
        if not src:
            return
        if len(path) == 1:
            have = "dict"
        else:
            if path[1] not in src.outputs:
                near = difflib.get_close_matches(path[1], src.outputs.keys(), n=1)
                det.append(f"[{sid}] {where}: {root} ({src.name}) has no output '{path[1]}'"
                           + (f" — did you mean '{near[0]}'?" if near else f" — outputs: {', '.join(src.outputs)}"))
                return
            have = src.outputs[path[1]] if len(path) == 2 else "any"
        if want and not _compatible(have, want):
            det.append(f"[{sid}] {where}: '{'.'.join(path)}' is {have} but the parameter needs {want.rstrip('?')}")

    for i, s in enumerate(plan.steps):
        spec = REGISTRY.get(s.action)
        for k, v in s.params.items():
            want = spec.inputs.get(k) if spec else None
            exact = isinstance(v, str) and expr.REF_RE.match(v.strip())
            for path in expr.value_refs(v):
                check_path(i, s.id, path, f"param '{k}'", want if exact else None)
    add("refs", "References & types", det, warn)

    # 7. conditions
    det = []
    for i, s in enumerate(plan.steps):
        if not s.when:
            continue
        try:
            for path in expr.references(s.when):
                check_path(i, s.id, path, "condition")
        except expr.ExprError as e:
            det.append(f"[{s.id}] condition: {e}")
    add("conditions", "Conditions", det)

    # 8. company policy
    det = []
    has_approval = [i for i, s in enumerate(plan.steps) if s.action == "request_approval"]
    for i, s in enumerate(plan.steps):
        spec = REGISTRY.get(s.action)
        if s.on_error.retry < 0 or s.on_error.retry > 5:
            det.append(f"[{s.id}] retry must be between 0 and 5")
        if s.on_error.fallback not in ALLOWED_FALLBACKS:
            det.append(f"[{s.id}] fallback '{s.on_error.fallback}' not allowed; use escalate_to_human or skip")
        if s.action == "request_approval" and not s.requires_approval:
            det.append(f"[{s.id}] request_approval must have requires_approval: true")
        if spec and spec.money:
            if not s.when:
                det.append(f"[{s.id}] '{s.action}' moves money and must be guarded by a condition (no unconditional posting)")
            if not any(j < i for j in has_approval):
                det.append(f"[{s.id}] '{s.action}' needs a request_approval step before it (SOP approval limits)")
        if spec and spec.side_effect and not spec.money and not s.when and not s.requires_approval:
            warnings.append(f"[{s.id}] '{s.action}' changes the outside world on every task (no condition)")
    add("policy", "Company policy", det)

    report = {"ok": not errors, "checks": checks, "errors": errors, "warnings": warnings}
    return report, plan.model_dump()