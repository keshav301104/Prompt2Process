"""Learns expense categories from the company's own bookings and from human corrections.

Once trained, confident predictions are made locally (no AI call). Uncertain ones still go to Gemma.
Method: TF-IDF (word + character n-grams) + logistic regression — trains in well under a second on a CPU.
"""

import threading
from datetime import UTC, datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import FeatureUnion, Pipeline

from .. import company as co
from .. import db

_lock = threading.Lock()
_models: dict[str, dict] = {}  # employee_id -> {"pipe", "labels", ...}
CONFIDENCE_THRESHOLD = 0.6


def invoice_text(vendor_name: str | None, items: list | None) -> str:
    descs = " ; ".join((i.get("description") or "") for i in (items or []) if isinstance(i, dict))
    return f"{vendor_name or ''} :: {descs}".strip()


def _training_data(employee_id: str) -> tuple[list[str], list[str], int]:
    X, y = [], []
    for r in co.posted_invoices():  # the company's own past bookings
        if r.get("category"):
            X.append(invoice_text(r.get("vendor_name"), []))
            y.append(r["category"])
    corr = db.corrections(employee_id, "category")
    for c in corr:  # human corrections weigh more
        for _ in range(3):
            X.append(c["text"])
            y.append(c["value"])
    return X, y, len(corr)


def train(employee_id: str) -> dict:
    X, y, n_corr = _training_data(employee_id)
    labels = sorted(set(y))
    if len(labels) < 2:
        return status(employee_id) | {"error": "need at least two categories to learn"}
    pipe = Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
                        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True)),
                    ]
                ),
            ),
            ("clf", LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")),
        ]
    )
    cv = None
    counts = np.unique(y, return_counts=True)[1]
    k = int(min(5, counts.min()))
    if k >= 2:
        cv = float(cross_val_score(pipe, X, y, cv=StratifiedKFold(k, shuffle=True, random_state=0)).mean())
    pipe.fit(X, y)
    with _lock:
        prev = _models.get(employee_id, {})
        _models[employee_id] = {
            "pipe": pipe,
            "labels": labels,
            "n_examples": len(X),
            "n_corrections": n_corr,
            "cv_accuracy": cv,
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "ai_calls_saved": prev.get("ai_calls_saved", 0),
        }
    db.audit(
        "system",
        "model_trained",
        f"category model for {employee_id}: {len(X)} examples, "
        f"{n_corr} corrections, cv accuracy {cv if cv is None else round(cv, 3)}",
    )
    return status(employee_id)


def predict(employee_id: str, text: str) -> tuple[str, float] | None:
    with _lock:
        m = _models.get(employee_id)
    if not m:
        return None
    proba = m["pipe"].predict_proba([text])[0]
    i = int(np.argmax(proba))
    return m["pipe"].classes_[i], float(proba[i])


def note_saved_call(employee_id: str) -> None:
    with _lock:
        if employee_id in _models:
            _models[employee_id]["ai_calls_saved"] += 1


def status(employee_id: str) -> dict:
    with _lock:
        m = _models.get(employee_id)
    n_corr = len(db.corrections(employee_id, "category"))
    if not m:
        return {
            "model_trained": False,
            "labels": [],
            "n_examples": 0,
            "n_corrections": n_corr,
            "cv_accuracy": None,
            "last_trained_at": None,
            "ai_calls_saved": 0,
            "method": "TF-IDF (word + char n-grams) + logistic regression",
        }
    return {
        "model_trained": True,
        "labels": m["labels"],
        "n_examples": m["n_examples"],
        "n_corrections": n_corr,
        "cv_accuracy": None if m["cv_accuracy"] is None else round(m["cv_accuracy"], 3),
        "last_trained_at": m["trained_at"],
        "ai_calls_saved": m["ai_calls_saved"],
        "method": "TF-IDF (word + char n-grams) + logistic regression",
    }
