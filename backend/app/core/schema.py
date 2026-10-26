"""The workflow program format. The LLM writes this; the checker verifies it; the runner executes it."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OnError(BaseModel):
    model_config = ConfigDict(extra="ignore")
    retry: int = 1
    fallback: str | None = None  # name of an action to run if all retries fail (e.g. escalate_to_human)


class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    title: str = ""
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    when: str | None = None  # safe boolean expression, e.g. "s10.route == 'approval'"
    on_error: OnError = Field(default_factory=OnError)
    requires_approval: bool = False  # SOP says a human must sign off before this step runs
    side_effect: bool = False  # filled in from the action registry (changes the outside world)


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    description: str = ""
    steps: list[Step]


ROUTES = ["auto_post", "approval", "reject", "human_review"]

ISSUE_TYPES = [
    "duplicate",
    "gstin_invalid",
    "overbilling",
    "qty_mismatch",
    "totals_mismatch",
    "tax_type_mismatch",
    "anomaly",
    "injection",
    "unknown_vendor",
    "missing_po",
    "low_confidence",
]
REJECT_TYPES = {"duplicate", "gstin_invalid"}
REVIEW_TYPES = {
    "overbilling",
    "qty_mismatch",
    "totals_mismatch",
    "tax_type_mismatch",
    "anomaly",
    "injection",
    "unknown_vendor",
    "missing_po",
    "low_confidence",
    "po_vendor_mismatch",
    "bank_mismatch",
    "gstin_missing",
}
