"""A tiny, safe expression language for `when` conditions and `$references`.

Allowed:  s10.route == 'approval' and s2.total >= 10000 ;  not s6.is_duplicate ;  s3.level in [2, 3] ;  len(s7.issues) > 0
Formulas may call a small whitelist: len, min, max, round, abs, emi(principal, rate, months), days_between(a, b), today().
Nothing else (no imports, no attribute magic, no arbitrary calls).
"""

import ast
import re
from datetime import date


def _d(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _days_between(a, b):
    da, db = _d(a), _d(b)
    return (db - da).days if da and db else None


def _emi(principal, annual_rate_pct, months):
    """Monthly instalment of a loan (reducing balance)."""
    try:
        p, r, n = float(principal), float(annual_rate_pct) / 1200, int(months)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return round(p / n, 2) if r == 0 else round(p * r * (1 + r) ** n / ((1 + r) ** n - 1), 2)


def _safe(fn):
    def wrapped(*args):
        try:
            return fn(*args)
        except (TypeError, ValueError):
            return None

    return wrapped


# the only functions a condition / formula may call
FUNCS = {
    "len": _safe(lambda v: len(v) if v is not None else 0),
    "min": _safe(min),
    "max": _safe(max),
    "round": _safe(round),
    "abs": _safe(abs),
    "emi": _emi,
    "days_between": _days_between,
    "today": lambda: date.today().isoformat(),
}

_NAMES_OK = {"true": True, "false": False, "null": None, "none": None, "True": True, "False": False, "None": None}
REF_RE = re.compile(r"^\$([A-Za-z_][\w]*)((?:\.[A-Za-z_][\w]*)*)$")
INTERP_RE = re.compile(r"\$\{([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\}")


class ExprError(ValueError):
    pass


def _normalise(expr: str) -> str:
    e = expr.strip().replace("$", "")
    e = e.replace("&&", " and ").replace("||", " or ")
    e = re.sub(r"!(?!=)", " not ", e)
    return e


def parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(_normalise(expr), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"cannot parse condition '{expr}': {e.msg}") from e
    _validate(tree.body)
    return tree


def _validate(node: ast.AST) -> None:
    allowed = (
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.USub,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Is,
        ast.IsNot,
        ast.Name,
        ast.Load,
        ast.Attribute,
        ast.Constant,
        ast.List,
        ast.Tuple,
        ast.Subscript,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
    )
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id in FUNCS) or n.keywords:
                raise ExprError(f"only these functions may be called: {', '.join(FUNCS)}")
            continue
        if not isinstance(n, allowed):
            raise ExprError(f"'{type(n).__name__}' is not allowed in a condition")


def references(expr: str) -> list[list[str]]:
    """All dotted paths used in an expression, e.g. [['s10', 'route'], ['s2', 'total']]."""
    tree = parse(expr)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            path: list[str] = []
            cur: ast.expr = n
            while isinstance(cur, ast.Attribute):
                path.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                path.append(cur.id)
                out.append(list(reversed(path)))
        elif isinstance(n, ast.Name) and n.id not in _NAMES_OK and n.id not in FUNCS:
            out.append([n.id])
    # keep only the longest paths (drop prefixes of attribute chains)
    longest = [p for p in out if not any(q != p and q[: len(p)] == p for q in out)]
    return longest


def evaluate(expr: str, scope: dict) -> bool:
    return bool(_eval(parse(expr).body, scope))


def compute(expr: str, scope: dict):
    """Evaluate a formula and return its value (not just true/false)."""
    return _eval(parse(expr).body, scope)


def _get(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _eval(n, scope):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        if n.id in _NAMES_OK:
            return _NAMES_OK[n.id]
        return scope.get(n.id)
    if isinstance(n, ast.Attribute):
        return _get(_eval(n.value, scope), n.attr)
    if isinstance(n, ast.Subscript):
        base, idx = _eval(n.value, scope), _eval(n.slice, scope)
        try:
            return base[idx]
        except (KeyError, IndexError, TypeError):
            return None
    if isinstance(n, (ast.List, ast.Tuple)):
        return [_eval(e, scope) for e in n.elts]
    if isinstance(n, ast.UnaryOp):
        v = _eval(n.operand, scope)
        return (not v) if isinstance(n.op, ast.Not) else -(v or 0)
    if isinstance(n, ast.BoolOp):
        vals = (_eval(v, scope) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.BinOp):
        a, b = _eval(n.left, scope), _eval(n.right, scope)
        if a is None or b is None:
            return None
        try:
            if isinstance(n.op, ast.Div):
                return a / b if b else None
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b}[type(n.op)]()
        except TypeError:
            return None
    if isinstance(n, ast.Call):
        return FUNCS[n.func.id](*[_eval(a, scope) for a in n.args])
    if isinstance(n, ast.Compare):
        left = _eval(n.left, scope)
        for op, comp in zip(n.ops, n.comparators, strict=True):
            right = _eval(comp, scope)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    raise ExprError(f"unsupported node {type(n).__name__}")


# ------------------------------------------------------------------ $references in params
def resolve_value(value, scope: dict):
    """'$s2.total' -> the value; '...${s2.vendor_name}...' -> interpolated string; dict/list recursively."""
    if isinstance(value, str):
        m = REF_RE.match(value.strip())
        if m:
            cur = scope.get(m.group(1))
            for part in [p for p in m.group(2).split(".") if p]:
                cur = _get(cur, part)
            return cur
        if "${" in value:

            def sub(mm):
                cur = scope
                for part in mm.group(1).split("."):
                    cur = _get(cur, part)
                if cur is None:
                    return ""
                if isinstance(cur, list):
                    return "; ".join(str(x) for x in cur)
                return f"{cur:,.2f}" if isinstance(cur, float) else str(cur)

            return INTERP_RE.sub(sub, value)
        return value
    if isinstance(value, dict):
        return {k: resolve_value(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, scope) for v in value]
    return value


def value_refs(value) -> list[list[str]]:
    """All reference paths inside a param value."""
    out = []
    if isinstance(value, str):
        m = REF_RE.match(value.strip())
        if m:
            out.append([m.group(1)] + [p for p in m.group(2).split(".") if p])
        for mm in INTERP_RE.finditer(value):
            out.append(mm.group(1).split("."))
    elif isinstance(value, dict):
        for v in value.values():
            out += value_refs(v)
    elif isinstance(value, list):
        for v in value:
            out += value_refs(v)
    return out


def _compare(op: ast.cmpop, left, right) -> bool:
    try:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.In):
            return left in (right or [])
        if isinstance(op, ast.NotIn):
            return left not in (right or [])
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right
    except TypeError:
        return False  # e.g. None < 5 -> the condition is simply false
    raise ExprError(f"unsupported comparison {type(op).__name__}")
