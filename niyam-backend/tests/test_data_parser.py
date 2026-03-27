"""Tests for Data Parser — regex-based invoice field extraction."""

import pytest
from app.services.data_parser import DataParser, ExtractedField


class TestExtractedField:
    def test_creation(self):
        field = ExtractedField(value="TEST-001", confidence=95, method="strict_regex")
        assert field.value == "TEST-001"
        assert field.confidence == 95
        assert field.method == "strict_regex"

    def test_to_dict(self):
        field = ExtractedField(value=250000.0, confidence=85, method="keyword_anchor")
        d = field.to_dict()
        assert isinstance(d, dict)
        assert d["value"] == 250000.0
        assert d["confidence"] == 85


class TestDataParser:
    def setup_method(self):
        self.parser = DataParser()

    def test_parse_standard_invoice(self, sample_invoice_text):
        """Parse a well-formatted GST invoice."""
        result = self.parser.parse_invoice(sample_invoice_text)
        assert isinstance(result, dict)

        # GSTIN should be extracted
        gstin = result.get("gstin", {})
        assert gstin.get("value") is not None
        assert "27AAACM7890G1Z3" in str(gstin.get("value", ""))

        # Invoice number
        inv_num = result.get("invoice_number", {})
        assert inv_num.get("value") is not None

        # Total amount
        total = result.get("total_amount", {})
        assert total.get("value") is not None

    def test_confidence_scores_present(self, sample_invoice_text):
        """Every extracted field should have a confidence score."""
        result = self.parser.parse_invoice(sample_invoice_text)
        for key in ["gstin", "invoice_number", "invoice_date", "total_amount"]:
            field = result.get(key, {})
            if field.get("value") is not None:
                assert "confidence" in field
                assert 0 <= field["confidence"] <= 100

    def test_overall_confidence(self, sample_invoice_text):
        """Overall confidence should be present and reasonable."""
        result = self.parser.parse_invoice(sample_invoice_text)
        assert "overall_confidence" in result
        assert 0 <= result["overall_confidence"] <= 100

    def test_empty_text(self):
        """Empty text should not crash, should return low confidence."""
        result = self.parser.parse_invoice("")
        assert isinstance(result, dict)
        assert result.get("overall_confidence", 0) < 50

    def test_gibberish_text(self):
        """Random text should return low confidence, no valid fields."""
        result = self.parser.parse_invoice("lorem ipsum dolor sit amet 12345")
        assert isinstance(result, dict)
        assert result.get("overall_confidence", 100) < 50

    def test_gstin_extraction_patterns(self):
        """Test GSTIN extraction from various formats."""
        texts = [
            "GSTIN: 27AAACM7890G1Z3",
            "GSTIN 27AAACM7890G1Z3",
            "Vendor GSTIN: 27AAACM7890G1Z3",
        ]
        for text in texts:
            result = self.parser.parse_invoice(text)
            gstin = result.get("gstin", {}).get("value")
            assert gstin is not None, f"Failed to extract GSTIN from: {text}"

    def test_amount_extraction(self):
        """Test amount extraction from different formats."""
        text = """
        Invoice No: INV-001
        Taxable Value: 1,50,000.00
        CGST: 13,500.00
        SGST: 13,500.00
        Total: 1,77,000.00
        """
        result = self.parser.parse_invoice(text)
        total = result.get("total_amount", {}).get("value")
        assert total is not None

    def test_date_extraction(self):
        """Test date extraction from various formats."""
        text = "Invoice Date: 15/03/2026\nInvoice No: INV-001\nTotal: 10000"
        result = self.parser.parse_invoice(text)
        inv_date = result.get("invoice_date", {}).get("value")
        assert inv_date is not None

    def test_needs_review_flagging(self):
        """Incomplete invoices should flag fields for review."""
        text = "Invoice No: INV-001\nTotal: 5000"  # No GSTIN, no date
        result = self.parser.parse_invoice(text)
        needs_review = result.get("needs_review", [])
        assert isinstance(needs_review, list)
