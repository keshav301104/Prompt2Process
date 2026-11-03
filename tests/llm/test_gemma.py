import pytest
from backend.app.llm.gemma import parse_json

@pytest.mark.parametrize("raw_text, expected", [
    # Clean JSON
    ('{"status": "ok"}', {"status": "ok"}),
    
    # Markdown fences (common LLM output artifact)
    ('```json\n{"route": "auto_post"}\n```', {"route": "auto_post"}),
    
    # Gemma 4 <think> tags (common instruct model artifact)
    ('<think>\nComparing invoice to PO...\n</think>\n{"route": "approval"}', {"route": "approval"}),
    
    # Combined artifacts (Text + Tags + Fences)
    ('Here is the plan:\n<think>checking limits</think>\n```json\n{"step": 1}\n```', {"step": 1}),
])
def test_parse_json_strips_artifacts(raw_text, expected):
    """Verify the parser strips <think> blocks and markdown fences to extract the valid JSON."""
    result = parse_json(raw_text)
    assert result == expected

def test_parse_json_raises_value_error_on_garbage():
    """Ensure non-JSON responses throw a ValueError to trigger the repair call."""
    with pytest.raises(ValueError):
        parse_json("I cannot fulfill this request because the invoice is missing.")