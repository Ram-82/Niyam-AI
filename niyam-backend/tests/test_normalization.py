"""Tests for Normalization — type enforcement, GST reconciliation, review codes."""

import pytest
from app.services.normalization import normalize_invoice, NormalizedInvoice, ReviewCode


class TestNormalizeInvoice:
    def test_valid_parsed_data(self):
        """Well-formed parsed data should normalize cleanly."""
        parsed = {
            "gstin": {"value": "27AAACM7890G1Z3", "confidence": 95},
            "invoice_number": {"value": "TEX/2026/0087", "confidence": 90},
            "invoice_date": {"value": "2026-03-02", "confidence": 92},
            "vendor_name": {"value": "Mumbai Cotton Mills", "confidence": 85},
            "taxable_amount": {"value": 250000, "confidence": 88},
            "cgst": {"value": 22500, "confidence": 90},
            "sgst": {"value": 22500, "confidence": 90},
            "igst": {"value": 0, "confidence": 95},
            "gst_amount": {"value": 45000, "confidence": 90},
            "total_amount": {"value": 295000, "confidence": 92},
            "hsn_codes": {"value": ["52051200", "52052400"], "confidence": 80},
        }

        result = normalize_invoice(parsed, "test-inv-001")
        assert isinstance(result, NormalizedInvoice)
        assert result.gstin == "27AAACM7890G1Z3"
        assert result.invoice_number == "TEX/2026/0087"
        assert result.taxable_amount == 250000
        assert result.total_amount == 295000
        assert result.cgst == 22500
        assert result.sgst == 22500
        assert result.needs_review is False

    def test_to_dict(self):
        """NormalizedInvoice.to_dict() should return serializable dict."""
        parsed = {
            "gstin": {"value": "27AAACM7890G1Z3", "confidence": 95},
            "invoice_number": {"value": "TEST-001", "confidence": 90},
            "invoice_date": {"value": "2026-03-01", "confidence": 90},
            "total_amount": {"value": 10000, "confidence": 85},
            "taxable_amount": {"value": 8475, "confidence": 85},
            "cgst": {"value": 763, "confidence": 85},
            "sgst": {"value": 762, "confidence": 85},
            "igst": {"value": 0, "confidence": 95},
            "gst_amount": {"value": 1525, "confidence": 85},
            "vendor_name": {"value": "Test Vendor", "confidence": 80},
            "hsn_codes": {"value": [], "confidence": 50},
        }
        result = normalize_invoice(parsed, "test-001")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "invoice_id" in d
        assert "confidence_score" in d

    def test_missing_gstin_flags_review(self):
        """Missing GSTIN should trigger needs_review."""
        parsed = {
            "gstin": {"value": None, "confidence": 0},
            "invoice_number": {"value": "INV-001", "confidence": 90},
            "invoice_date": {"value": "2026-03-01", "confidence": 90},
            "total_amount": {"value": 10000, "confidence": 85},
            "taxable_amount": {"value": 8475, "confidence": 85},
            "cgst": {"value": 763, "confidence": 85},
            "sgst": {"value": 762, "confidence": 85},
            "igst": {"value": 0, "confidence": 95},
            "gst_amount": {"value": 1525, "confidence": 85},
            "vendor_name": {"value": "Test Vendor", "confidence": 80},
            "hsn_codes": {"value": [], "confidence": 50},
        }
        result = normalize_invoice(parsed, "test-002")
        assert result.needs_review is True
        assert ReviewCode.MISSING_GSTIN in result.review_reasons

    def test_low_confidence_flags_review(self):
        """Low overall confidence should trigger needs_review."""
        parsed = {
            "gstin": {"value": "27AAACM7890G1Z3", "confidence": 30},
            "invoice_number": {"value": "INV-001", "confidence": 25},
            "invoice_date": {"value": "2026-03-01", "confidence": 20},
            "total_amount": {"value": 10000, "confidence": 30},
            "taxable_amount": {"value": 8475, "confidence": 25},
            "cgst": {"value": 763, "confidence": 25},
            "sgst": {"value": 762, "confidence": 25},
            "igst": {"value": 0, "confidence": 50},
            "gst_amount": {"value": 1525, "confidence": 25},
            "vendor_name": {"value": "Test Vendor", "confidence": 20},
            "hsn_codes": {"value": [], "confidence": 10},
        }
        result = normalize_invoice(parsed, "test-003")
        assert result.needs_review is True
        assert ReviewCode.LOW_CONFIDENCE in result.review_reasons

    def test_gst_reconciliation_intrastate(self):
        """CGST+SGST should be reconciled for intra-state."""
        parsed = {
            "gstin": {"value": "27AAACM7890G1Z3", "confidence": 95},
            "invoice_number": {"value": "INV-001", "confidence": 90},
            "invoice_date": {"value": "2026-03-01", "confidence": 90},
            "total_amount": {"value": 118000, "confidence": 90},
            "taxable_amount": {"value": 100000, "confidence": 90},
            "cgst": {"value": 9000, "confidence": 90},
            "sgst": {"value": 9000, "confidence": 90},
            "igst": {"value": 0, "confidence": 95},
            "gst_amount": {"value": 18000, "confidence": 90},
            "vendor_name": {"value": "Test Vendor", "confidence": 80},
            "hsn_codes": {"value": [], "confidence": 50},
        }
        result = normalize_invoice(parsed, "test-004")
        assert result.cgst == 9000
        assert result.sgst == 9000
        assert result.igst == 0

    def test_amount_normalization_string(self):
        """String amounts like '₹6,500.00' should be converted to float."""
        parsed = {
            "gstin": {"value": "27AAACM7890G1Z3", "confidence": 95},
            "invoice_number": {"value": "INV-001", "confidence": 90},
            "invoice_date": {"value": "2026-03-01", "confidence": 90},
            "total_amount": {"value": "₹6,500.00", "confidence": 85},
            "taxable_amount": {"value": "5,508.47", "confidence": 85},
            "cgst": {"value": "495.76", "confidence": 85},
            "sgst": {"value": "495.77", "confidence": 85},
            "igst": {"value": 0, "confidence": 95},
            "gst_amount": {"value": "991.53", "confidence": 85},
            "vendor_name": {"value": "Test Vendor", "confidence": 80},
            "hsn_codes": {"value": [], "confidence": 50},
        }
        result = normalize_invoice(parsed, "test-005")
        assert isinstance(result.total_amount, float)
        assert result.total_amount == 6500.0
