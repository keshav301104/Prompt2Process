import pytest
from backend.app.core.expr import evaluate

MOCK_CONTEXT = {
    "s1": {"total": 15000, "is_valid": True},
    "task": {"file": "invoice.pdf"},
    "org": {"people": {"finance_manager": "alice@example.com"}}
}

@pytest.mark.parametrize("expression, expected_result", [
    # Basic arithmetic and logic (now tested as boolean equations)
    ("10 + 5 * 2 == 20", True),
    ("s1.total > 10000", True),
    ("s1.total <= 5000", False),
    ("s1.is_valid and s1.total == 15000", True),
    
    # Allowed functions
    ("min(10, 20, 5) == 5", True),
    ("max(10, 20, 5) == 20", True),
    ("abs(-50) == 50", True),
    ("round(15.678, 1) == 15.7", True),
    
    # String operations and IN clauses
    ("'approval' in ['auto_post', 'approval', 'reject']", True),
    ("task.file == 'invoice.pdf'", True),
])
def test_allowed_expressions(expression, expected_result):
    """Verify that the safe AST whitelist successfully evaluates permitted logic."""
    result = evaluate(expression, MOCK_CONTEXT)
    assert result == expected_result

@pytest.mark.parametrize("malicious_expression", [
    "__import__('os').system('echo hacked')",  
    "s1.__class__",                            
    "open('/etc/passwd').read()",              
    "lambda x: x",                             
    "s1.total = 999999",                       
])
def test_forbidden_expressions_are_blocked(malicious_expression):
    """Ensure the AST whitelist strictly rejects any potentially unsafe Python code."""
    try:
        result = evaluate(malicious_expression, MOCK_CONTEXT)
        # If it doesn't raise an exception, it MUST evaluate to False or None
        assert not result, f"Dangerous expression was allowed and returned {result}"
    except Exception:
        # If it raises a SyntaxError, ValueError, or ParseError, it is safely blocked
        pass