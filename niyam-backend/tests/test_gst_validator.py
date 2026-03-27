"""Tests for GST Validator — GSTIN format, tax calculations, ITC eligibility."""

import pytest
from app.services.gst_validator import (
    validate_gstin_format,
    validate_gst_structure,
    validate_tax_calculation,
    validate_total_amount,
    validate_invoice_date,
    validate_itc_eligibility,
    validate_invoice,
)


# ============================================================
# GSTIN Format Validation
# ============================================================

class TestGSTINFormat:
    def test_valid_gstin(self):
        result = validate_gstin_format("27AAACM7890G1Z3")
        assert result is None  # valid = no issue

    def test_missing_gstin(self):
        result = validate_gstin_format("")
        assert result is not None
        assert result["type"] == "GSTIN_MISSING"

    def test_none_gstin(self):
        result = validate_gstin_format(None)
        assert result is not None

    def test_wrong_length(self):
        result = validate_gstin_format("27AAACM")
        assert result is not None
        assert "length" in result["type"].lower() or "invalid" in result["type"].lower()

    def test_invalid_state_code(self):
        result = validate_gstin_format("99AAACM7890G1Z3")
        assert result is not None

    def test_valid_state_codes(self):
        # State code 01 (Jammu & Kashmir) to 37 (Andhra Pradesh)
        for code in ["01", "07", "27", "29", "33", "37"]:
            gstin = f"{code}AAACM7890G1Z3"
            result = validate_gstin_format(gstin)
            # Should not flag state code as invalid
            if result and result["type"] == "GSTIN_INVALID_STATE":
                pytest.fail(f"State code {code} should be valid")


# ============================================================
# GST Structure Validation
# ============================================================

class TestGSTStructure:
    def test_valid_intrastate(self):
        """CGST + SGST (intra-state) is valid."""
        result = validate_gst_structure({"cgst": 9000, "sgst": 9000, "igst": 0})
        assert result is None

    def test_valid_interstate(self):
        """IGST only (inter-state) is valid."""
        result = validate_gst_structure({"cgst": 0, "sgst": 0, "igst": 18000})
        assert result is None

    def test_mixed_gst_invalid(self):
        """CGST+SGST AND IGST together is invalid."""
        result = validate_gst_structure({"cgst": 9000, "sgst": 9000, "igst": 18000})
        assert result is not None

    def test_cgst_sgst_mismatch(self):
        """CGST and SGST should be equal (within tolerance)."""
        result = validate_gst_structure({"cgst": 9000, "sgst": 5000, "igst": 0})
        assert result is not None


# ============================================================
# Tax Calculation Validation
# ============================================================

class TestTaxCalculation:
    def test_valid_18_percent(self):
        """18% GST on ₹100,000 = ₹18,000."""
        result = validate_tax_calculation(100000, {"cgst": 9000, "sgst": 9000, "igst": 0})
        assert result is None

    def test_valid_5_percent(self):
        """5% GST on ₹100,000 = ₹5,000."""
        result = validate_tax_calculation(100000, {"cgst": 2500, "sgst": 2500, "igst": 0})
        assert result is None

    def test_invalid_rate(self):
        """Non-standard rate should be flagged."""
        result = validate_tax_calculation(100000, {"cgst": 7500, "sgst": 7500, "igst": 0})
        assert result is not None

    def test_zero_taxable(self):
        """Zero taxable value should not crash."""
        result = validate_tax_calculation(0, {"cgst": 0, "sgst": 0, "igst": 0})
        # Should handle gracefully (return None or skip)
        assert True  # No crash


# ============================================================
# Total Amount Validation
# ============================================================

class TestTotalAmount:
    def test_valid_total(self):
        """Total = taxable + CGST + SGST."""
        result = validate_total_amount(295000, 250000, {"cgst": 22500, "sgst": 22500, "igst": 0})
        assert result is None

    def test_mismatched_total(self):
        """Total doesn't match taxable + GST."""
        result = validate_total_amount(300000, 250000, {"cgst": 22500, "sgst": 22500, "igst": 0})
        assert result is not None

    def test_slight_rounding(self):
        """Small rounding difference (₹1) should be tolerated."""
        result = validate_total_amount(295001, 250000, {"cgst": 22500, "sgst": 22500, "igst": 0})
        assert result is None


# ============================================================
# Invoice Date Validation
# ============================================================

class TestInvoiceDate:
    def test_valid_recent_date(self):
        result = validate_invoice_date("2026-03-01")
        # Should not be flagged as invalid (may flag as recent/not-in-2B-yet)
        if result:
            assert result["type"] != "INVALID_DATE"

    def test_invalid_date_format(self):
        result = validate_invoice_date("not-a-date")
        assert result is not None

    def test_future_date(self):
        result = validate_invoice_date("2099-12-31")
        assert result is not None


# ============================================================
# ITC Eligibility
# ============================================================

class TestITCEligibility:
    def test_fully_eligible(self):
        result = validate_itc_eligibility(
            gstin_valid=True, gst_total=18000,
            invoice_complete=True, date_issue=None,
        )
        assert result["eligible"] is True
        assert result["itc_amount"] == 18000
        assert result["itc_at_risk"] == 0

    def test_no_gstin_blocks_itc(self):
        result = validate_itc_eligibility(
            gstin_valid=False, gst_total=18000,
            invoice_complete=True, date_issue=None,
        )
        assert result["eligible"] is False
        assert result["itc_amount"] == 0  # ITC blocked entirely when GSTIN invalid
        assert any("gstin" in r.lower() for r in result["reasons"])

    def test_zero_gst(self):
        result = validate_itc_eligibility(
            gstin_valid=True, gst_total=0,
            invoice_complete=True, date_issue=None,
        )
        assert result["itc_amount"] == 0


# ============================================================
# Full Invoice Validation
# ============================================================

class TestValidateInvoice:
    def test_valid_invoice(self, sample_invoice_data):
        result = validate_invoice(sample_invoice_data)
        assert result["is_valid"] is True
        assert result["compliance_score"] > 70
        assert isinstance(result["issues"], list)

    def test_missing_gstin_invoice(self, sample_invoice_data):
        sample_invoice_data["vendor_gstin"] = ""
        result = validate_invoice(sample_invoice_data)
        assert result["is_valid"] is False
        assert any("gstin" in i.get("type", "").lower() or "gstin" in i.get("message", "").lower()
                    for i in result["issues"])

    def test_empty_invoice(self):
        result = validate_invoice({})
        assert isinstance(result, dict)
        assert "is_valid" in result
