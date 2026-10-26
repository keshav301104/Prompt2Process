"""Reversible masking of Indian personal / financial identifiers before text is sent to any model.

The model sees tokens like [PHONE_1]; we map them back afterwards, so the answer is still useful
but the raw identifiers never leave the machine.
"""
import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("GSTIN", re.compile(r"\b[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("AADHAAR", re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b")),
    ("PHONE", re.compile(r"(?:\+91[\s-]?)?\b[6-9][0-9]{9}\b")),
    ("BANK_AC", re.compile(r"\b[0-9]{9,18}\b")),
]


def mask(text: str, keep: tuple[str, ...] = ()) -> tuple[str, dict[str, str]]:
    """Return (masked_text, token->original). Types in `keep` are left visible (e.g. GSTIN for extraction)."""
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}
    counters: dict[str, int] = {}

    for kind, pat in PATTERNS:
        if kind in keep:
            continue

        def repl(m: re.Match, kind=kind) -> str:
            original = m.group(0)
            if original in reverse:
                return reverse[original]
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            mapping[token] = original
            reverse[original] = token
            return token

        text = pat.sub(repl, text)
    return text, mapping


def unmask(obj, mapping: dict[str, str]):
    """Put the original values back into a model answer (str / dict / list)."""
    if not mapping:
        return obj
    if isinstance(obj, str):
        for token, original in mapping.items():
            obj = obj.replace(token, original)
        return obj
    if isinstance(obj, dict):
        return {k: unmask(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [unmask(v, mapping) for v in obj]
    return obj


def summary(mapping: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for token in mapping:
        kind = token.strip("[]").rsplit("_", 1)[0]
        out[kind] = out.get(kind, 0) + 1
    return out