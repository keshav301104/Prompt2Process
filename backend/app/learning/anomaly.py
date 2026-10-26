"""Amount anomaly detection: explainable ratio-to-vendor-median rule + Isolation Forest over the ledger."""

import math
import statistics
import threading

import numpy as np
from sklearn.ensemble import IsolationForest

from .. import company as co

_lock = threading.Lock()
_model: dict = {}


def _fit() -> None:
    rows = co.posted_invoices()
    by_vendor: dict[str, list[float]] = {}
    for r in rows:
        if r.get("vendor_id") and r["total"]:
            by_vendor.setdefault(r["vendor_id"], []).append(r["total"])
    medians = {v: statistics.median(t) for v, t in by_vendor.items()}
    X = [
        [math.log(r["total"]), math.log(r["total"] / medians[r["vendor_id"]])]
        for r in rows
        if r.get("vendor_id") in medians and r["total"]
    ]
    forest = None
    if len(X) >= 10:
        forest = IsolationForest(n_estimators=200, contamination="auto", random_state=7).fit(np.array(X))
    _model.update({"by_vendor": by_vendor, "medians": medians, "forest": forest})


def score(vendor_id: str, total: float, max_ratio: float = 4.0) -> dict:
    with _lock:
        if not _model:
            _fit()
    hist = _model["by_vendor"].get(vendor_id, [])
    if len(hist) < 3:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "ratio_to_median": None,
            "vendor_median": None,
            "reason": f"only {len(hist)} past invoices for this vendor — not enough history",
        }
    med = _model["medians"][vendor_id]
    ratio = total / med if med else 0
    iso = 0.0
    if _model["forest"] is not None:
        iso = float(-_model["forest"].score_samples(np.array([[math.log(total), math.log(max(ratio, 1e-6))]]))[0])
    is_anom = ratio >= max_ratio or ratio <= 1 / (max_ratio * 2)
    reason = (
        f"₹{total:,.0f} is {ratio:.1f}× this vendor's median of ₹{med:,.0f} over {len(hist)} past invoices "
        f"(threshold {max_ratio:g}×); isolation score {iso:.2f}"
    )
    return {
        "is_anomaly": is_anom,
        "score": round(iso, 3),
        "ratio_to_median": round(ratio, 2),
        "vendor_median": round(med, 2),
        "reason": reason,
    }


def reset() -> None:
    with _lock:
        _model.clear()
