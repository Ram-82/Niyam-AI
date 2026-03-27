"""Tests for ITC Matcher — reconciliation between purchase invoices and GSTR-2B."""

import pytest
from app.services.itc_matcher import ITCMatcher, MatchConfig, MatchResult, MatchType


class TestMatchConfig:
    def test_defaults(self):
        config = MatchConfig()
        assert config.amount_tolerance == 1.0
        assert config.gst_tolerance == 1.0
        assert config.fuzzy_invoice_number is True

    def test_custom_config(self):
        config = MatchConfig(amount_tolerance=5.0, fuzzy_invoice_number=False)
        assert config.amount_tolerance == 5.0
        assert config.fuzzy_invoice_number is False


class TestITCMatcher:
    def setup_method(self):
        self.matcher = ITCMatcher(MatchConfig(amount_tolerance=1.0))

    def test_exact_match(self):
        """Invoice matches GSTR-2B exactly."""
        invoices = [{
            "invoice_id": "inv-001",
            "invoice_number": "TEX/2026/0087",
            "vendor_gstin": "27AAACM7890G1Z3",
            "taxable_value": 250000,
            "cgst": 22500, "sgst": 22500, "igst": 0,
        }]
        # 2B entries use ctin/inum format (or gstin/invoice_number)
        gstr2b_entries = [{
            "ctin": "27AAACM7890G1Z3",
            "inum": "TEX/2026/0087",
            "taxable_value": 250000,
            "camt": 22500, "samt": 22500, "iamt": 0,
        }]

        results = self.matcher.match(invoices, gstr2b_entries)
        assert len(results) >= 1

        exact = [r for r in results if r.match_type == MatchType.EXACT_MATCH]
        assert len(exact) == 1
        assert exact[0].itc_at_risk == 0

    def test_missing_in_2b(self):
        """Invoice in books but not in GSTR-2B."""
        invoices = [{
            "invoice_id": "inv-002",
            "invoice_number": "BLR/EXP/2026-119",
            "vendor_gstin": "29BBBBB5555B2Z6",
            "taxable_value": 180000,
            "cgst": 0, "sgst": 0, "igst": 32400,
        }]
        gstr2b_entries = []  # Empty 2B

        results = self.matcher.match(invoices, gstr2b_entries)
        missing = [r for r in results if r.match_type == MatchType.MISSING_IN_2B]
        assert len(missing) == 1
        assert missing[0].itc_at_risk > 0

    def test_missing_in_invoices(self):
        """Entry in GSTR-2B but not in books."""
        invoices = []
        gstr2b_entries = [{
            "ctin": "33EEEEE6666E4Z2",
            "inum": "TN-2026-200",
            "taxable_value": 60000,
            "camt": 0, "samt": 0, "iamt": 10800,
        }]

        results = self.matcher.match(invoices, gstr2b_entries)
        missing = [r for r in results if r.match_type == MatchType.MISSING_IN_INVOICES]
        assert len(missing) == 1

    def test_partial_match(self):
        """Invoice matches but amounts differ slightly."""
        invoices = [{
            "invoice_id": "inv-003",
            "invoice_number": "DLH-2026-0033",
            "vendor_gstin": "07DDDDD4444D3Z9",
            "taxable_value": 92000,
            "cgst": 0, "sgst": 0, "igst": 16560,
        }]
        gstr2b_entries = [{
            "ctin": "07DDDDD4444D3Z9",
            "inum": "DLH-2026-0033",
            "taxable_value": 92500,  # ₹500 difference
            "camt": 0, "samt": 0, "iamt": 16650,
        }]

        results = self.matcher.match(invoices, gstr2b_entries)
        partial = [r for r in results if r.match_type == MatchType.PARTIAL_MATCH]
        assert len(partial) == 1

    def test_duplicate_detection(self):
        """Same invoice number twice in books."""
        invoices = [
            {
                "invoice_id": "inv-001a",
                "invoice_number": "TEX/2026/0087",
                "vendor_gstin": "27AAACM7890G1Z3",
                "taxable_value": 250000,
                "cgst": 22500, "sgst": 22500, "igst": 0,
            },
            {
                "invoice_id": "inv-001b",
                "invoice_number": "TEX/2026/0087",
                "vendor_gstin": "27AAACM7890G1Z3",
                "taxable_value": 250000,
                "cgst": 22500, "sgst": 22500, "igst": 0,
            },
        ]
        gstr2b_entries = [{
            "ctin": "27AAACM7890G1Z3",
            "inum": "TEX/2026/0087",
            "taxable_value": 250000,
            "camt": 22500, "samt": 22500, "iamt": 0,
        }]

        results = self.matcher.match(invoices, gstr2b_entries)
        duplicates = [r for r in results if r.match_type == MatchType.DUPLICATE_CLAIM]
        assert len(duplicates) >= 1

    def test_result_to_dict(self):
        """MatchResult.to_dict() returns serializable dict."""
        result = MatchResult()
        result.match_type = MatchType.EXACT_MATCH
        result.invoice_number = "TEST-001"
        result.vendor_gstin = "27AAACM7890G1Z3"
        result.eligible_itc = 45000
        result.claimed_itc = 45000
        result.itc_at_risk = 0
        result.severity = "none"
        result.confidence_score = 100
        result.risk_flag = False
        result.action_required = None
        result.recovery_priority = "none"
        result.action_type = "monitor"
        result.reason = "exact_match"
        result.due_date = None
        result.metadata = {}
        result.invoice_id = "inv-001"
        result.gstr2b_id = "2b-001"

        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["match_type"] == "exact_match"
        assert d["eligible_itc"] == 45000

    def test_empty_inputs(self):
        """Empty invoices and 2B should return empty results."""
        results = self.matcher.match([], [])
        assert results == []
