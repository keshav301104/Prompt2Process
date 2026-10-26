"""Late-payment risk for collections: logistic regression trained on the company's payment history."""

import threading

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .. import company as co

FEATURES = ["amount", "days_overdue_at_reminder", "avg_delay_days_history", "broken_promises", "customer_since_months"]
LABELS = {
    "amount": "invoice size",
    "days_overdue_at_reminder": "days overdue",
    "avg_delay_days_history": "usual payment delay",
    "broken_promises": "broken payment promises",
    "customer_since_months": "relationship length",
}
_lock = threading.Lock()
_m: dict = {}


def _fit() -> None:
    rows = [r for r in co.ar_history() if r.get("paid_late_30") is not None]
    if len(rows) < 20:
        _m["ok"] = False
        return
    X = np.array([[np.log1p(r[f] or 0) if f == "amount" else (r[f] or 0) for f in FEATURES] for r in rows])
    y = np.array([int(r["paid_late_30"]) for r in rows])
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=1000).fit(sc.transform(X), y)
    _m.update({"ok": True, "scaler": sc, "clf": clf, "n": len(rows), "acc": float(clf.score(sc.transform(X), y))})


def score(customer: dict) -> dict:
    with _lock:
        if not _m:
            _fit()
    if not _m.get("ok"):
        return {"risk": 0.5, "label": "medium", "top_factors": ["no payment history to learn from"]}
    feats = {
        "amount": customer.get("amount", 0),
        "days_overdue_at_reminder": customer.get("days_overdue", 0),
        "avg_delay_days_history": customer.get("avg_delay_days_history", 0),
        "broken_promises": customer.get("broken_promises", 0),
        "customer_since_months": customer.get("customer_since_months", 12),
    }
    x = np.array([[np.log1p(feats[f] or 0) if f == "amount" else (feats[f] or 0) for f in FEATURES]])
    z = _m["scaler"].transform(x)
    p = float(_m["clf"].predict_proba(z)[0, 1])
    contrib = sorted(zip(FEATURES, (z[0] * _m["clf"].coef_[0]), strict=False), key=lambda t: -t[1])
    top = [f"{LABELS[f]} ({feats[f]:g}) raises risk" for f, c in contrib[:2] if c > 0.15]
    label = "high" if p >= 0.7 else "medium" if p >= 0.4 else "low"
    return {
        "risk": round(p, 2),
        "label": label,
        "top_factors": top or ["no strong risk factors"],
        "model": f"logistic regression on {_m['n']} past invoices",
    }
