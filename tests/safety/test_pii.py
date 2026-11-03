import pytest
from backend.app.safety.pii import mask, unmask

def test_pii_masking_round_trip():
    """Verify that identifiers are completely removed and accurately restored."""
    original_text = "Contact vendor at finance@example.com or call +919876543210. PAN is ABCDE1234F and IFSC is SBIN0001234."
    
    # 1. Masking
    masked_text, mapping_dict = mask(original_text)
    
    # Ensure sensitive data is gone
    assert "finance@example.com" not in masked_text
    assert "+919876543210" not in masked_text
    assert "ABCDE1234F" not in masked_text
    assert "SBIN0001234" not in masked_text
    
    # 2. Unmasking
    restored_text = unmask(masked_text, mapping_dict)
    assert restored_text == original_text

def test_pii_keep_parameter_preserves_gstin():
    """Verify that passing keep=('GSTIN',) leaves the GSTIN visible but masks the PAN."""
    original_text = "Vendor GSTIN is 29ABCDE1234F1Z5. PAN is ABCDE1234F."
    
    # Masking but explicitly keeping GSTIN for the validate_gstin skill
    masked_text, mapping_dict = mask(original_text, keep=("GSTIN",))
    
    # The GSTIN remains fully visible
    assert "29ABCDE1234F1Z5" in masked_text
    
    # The standalone PAN is masked properly. 
    # (We cannot assert "ABCDE1234F" not in masked_text because it lives inside the GSTIN)
    assert "PAN is [PAN_1]" in masked_text