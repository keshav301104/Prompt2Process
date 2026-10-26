"""A tiny, safe expression language for `when` conditions and `$references`.

Allowed:  s10.route == 'approval' and s2.total >= 10000 ;  not s6.is_duplicate ;  s3.level in [2, 3] ;  len(s7.issues) > 0
Nothing else (no function calls except len, no imports, no attribute magic).
"""
import ast
import re

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
    allowed = (ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.Compare, ast.Eq, ast.NotEq, ast.Lt,
               ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.Name, ast.Load, ast.Attribute,
               ast.Constant, ast.List, ast.Tuple, ast.Subscript, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div)
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id == "len" and len(n.args) == 1):
                raise ExprError("only len(...) may be called in a condition")
            continue
        if not isinstance(n, allowed):
            raise ExprError(f"'{type(n).__name__}' is not allowed in a condition")


def references(expr: str) -> list[list[str]]:
    """All dotted paths used in an expression, e.g. [['s10', 'route'], ['s2', 'total']]."""
    tree = parse(expr)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            path, cur = [], n
            while isinstance(cur, ast.Attribute):
                path.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                path.append(cur.id)
                out.append(list(reversed(path)))
        elif isinstance(n, ast.Name) and n.id not in _NAMES_OK and n.id != "len":
            out.append([n.id])
    # keep only the longest paths (drop prefixes of attribute chains)
    longest = [p for p in out if not any(q != p and q[:len(p)] == p for q in out)]
    return longest


def evaluate(expr: str, scope: dict) -> bool:
    return bool(_eval(parse(expr).body, scope))


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
        a, b = _eval(n.left, scope) or 0, _eval(n.right, scope) or 0
        return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}.get(type(n.op), a / b if b else 0)
    if isinstance(n, ast.Call):
        v = _eval(n.args[0], scope)
        return len(v) if v is not None else 0
    if isinstance(n, ast.Compare):
        left = _eval(n.left, scope)
        for op, comp in zip(n.ops, n.comparators):
            right = _eval(comp, scope)
            try:
                ok = {ast.Eq: lambda: left == right, ast.NotEq: lambda: left != right,
                      ast.Lt: lambda: left < right, ast.LtE: lambda: left <= right,
                      ast.Gt: lambda: left > right, ast.GtE: lambda: left >= right,
                      ast.In: lambda: left in (right or []), ast.NotIn: lambda: left not in (right or []),
                      ast.Is: lambda: left is right, ast.IsNot: lambda: left is not right}[type(op)]()
            except TypeError:
                ok = False                 # e.g. None < 5 -> condition is simply false
            if not ok:
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