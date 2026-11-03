import pytest
from backend.app.core.checker import check
from backend.app.core.schema import Plan, Step

# CRITICAL: This import triggers the @action decorators to populate the REGISTRY
import backend.app.actions 

# A valid baseline step we can mutate for testing
VALID_STEP = {
    "id": "s1",
    "title": "Valid Read",
    "action": "read_invoice",
    "params": {"file": "$task.file"}
}

@pytest.mark.parametrize("mutations, expected_error_snippet", [
    ([{"id": "s1"}, {"id": "s1"}], "duplicate step id"),
    ([{"id": "s2", "action": "hack_mainframe", "params": {}}], "unknown action"),
    ([{"id": "s2", "action": "read_invoice", "params": {"wrong_param": "x"}}], "has no parameter"),    ([{"id": "s2", "action": "decide_route", "params": {}}], "missing required parameter"),
    ([{"id": "s2", "action": "check_totals", "params": {"invoice": "$s99.total"}}], "unknown step"),
    # Check 8: Money movement requires an approval gate
    ([{"id": "s2", "action": "post_journal_entry", "params": {"invoice": "$task.file"}}], "request_approval"),
])
def test_checker_edge_cases(mutations, expected_error_snippet):
    """Bombard the checker with policy and schema violations."""
    steps = []
    for mut in mutations:
        step_data = VALID_STEP.copy()
        step_data.update(mut)
        steps.append(Step(**step_data))
        
    plan = Plan(name="Test", description="Test Plan", steps=steps)
    
    # We pass role="ap" because read_invoice and post_journal_entry require the 'ap' role
    report, _ = check(plan, role="ap", tools=None)
    
    assert not report["ok"], "Expected plan to fail, but it passed"
    
    # Combine errors and make lowercase for robust matching
    error_messages = " ".join(report["errors"]).lower()
    assert expected_error_snippet.lower() in error_messages, f"Expected '{expected_error_snippet}' but got errors: {report['errors']}"

def test_valid_plan_passes():
    """Ensure a structurally perfect plan passes all 8 checks."""
    plan = Plan(
        name="Valid",
        description="Works",
        steps=[Step(**VALID_STEP)]
    )
    report, _ = check(plan, role="ap", tools=None)
    assert report["ok"], f"Valid plan failed with errors: {report['errors']}"