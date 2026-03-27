"""Tests for Rules Engine — deadline checking, invoice rules, penalty calculation."""

import pytest
from datetime import date

from app.services.rules.engine import RulesEngine
from app.services.rules.base import ComplianceFlag, Severity
from app.services.rules.deadline_rules import check_deadlines, generate_deadlines_for_year
from app.services.rules.penalty_rules import calculate_gst_penalty, calculate_tds_interest


# ============================================================
# Deadline Rules
# ============================================================

class TestDeadlineRules:
    def test_overdue_deadline(self):
        """Overdue deadline should produce CRITICAL flag."""
        deadlines = [{
            "type": "gst",
            "subtype": "GSTR-3B",
            "due_date": "2026-03-01",
            "status": "upcoming",
            "penalty_rate": 50,
        }]
        flags = check_deadlines(deadlines, today=date(2026, 3, 10))
        assert len(flags) >= 1
        assert flags[0].severity == Severity.CRITICAL
        assert "overdue" in flags[0].message.lower()

    def test_imminent_deadline(self):
        """Deadline within 3 days should produce ERROR flag."""
        deadlines = [{
            "type": "gst",
            "subtype": "GSTR-1",
            "due_date": "2026-03-12",
            "status": "upcoming",
            "penalty_rate": 50,
        }]
        flags = check_deadlines(deadlines, today=date(2026, 3, 10))
        assert len(flags) >= 1
        assert flags[0].severity == Severity.ERROR

    def test_approaching_deadline(self):
        """Deadline within 7 days should produce WARNING flag."""
        deadlines = [{
            "type": "gst",
            "subtype": "GSTR-3B",
            "due_date": "2026-03-15",
            "status": "upcoming",
            "penalty_rate": 50,
        }]
        flags = check_deadlines(deadlines, today=date(2026, 3, 10))
        assert len(flags) >= 1
        assert flags[0].severity == Severity.WARNING

    def test_completed_deadline_skipped(self):
        """Completed deadline should not produce any flag."""
        deadlines = [{
            "type": "gst",
            "subtype": "GSTR-3B",
            "due_date": "2026-03-01",
            "status": "completed",
            "penalty_rate": 50,
        }]
        flags = check_deadlines(deadlines, today=date(2026, 3, 10))
        assert len(flags) == 0

    def test_future_deadline_no_flag(self):
        """Deadline >30 days away should not produce any flag."""
        deadlines = [{
            "type": "gst",
            "subtype": "GSTR-3B",
            "due_date": "2026-06-20",
            "status": "upcoming",
            "penalty_rate": 50,
        }]
        flags = check_deadlines(deadlines, today=date(2026, 3, 10))
        assert len(flags) == 0


class TestDeadlineGeneration:
    def test_generates_gst_deadlines(self):
        """Should generate 12 GSTR-1 + 12 GSTR-3B + 1 GSTR-9 = 25 GST deadlines."""
        deadlines = generate_deadlines_for_year(2026)
        gst = [d for d in deadlines if d["type"] == "gst"]
        assert len(gst) == 25

    def test_generates_tds_deadlines(self):
        """Should generate TDS payment + quarterly return deadlines."""
        deadlines = generate_deadlines_for_year(2026)
        tds = [d for d in deadlines if d["type"] == "tds"]
        assert len(tds) > 12  # 12 monthly + quarterly

    def test_generates_roc_deadlines(self):
        """Should generate ROC deadlines."""
        deadlines = generate_deadlines_for_year(2026)
        roc = [d for d in deadlines if d["type"] == "roc"]
        assert len(roc) == 3  # AOC-4, MGT-7, DIR-3-KYC

    def test_tds_quarterly_fiscal_year_alignment(self):
        """TDS quarterly deadlines should span FY correctly."""
        deadlines = generate_deadlines_for_year(2025)
        tds_quarterly = [d for d in deadlines if d["type"] == "tds" and "Q" in d.get("subtype", "")]
        # Q1 → Jul 2025, Q2 → Oct 2025, Q3 → Jan 2026, Q4 → May 2026
        q3_deadlines = [d for d in tds_quarterly if "Q3" in d["subtype"]]
        for d in q3_deadlines:
            assert d["due_date"].startswith("2026-01"), f"Q3 should be Jan 2026, got {d['due_date']}"

        q4_deadlines = [d for d in tds_quarterly if "Q4" in d["subtype"]]
        for d in q4_deadlines:
            assert d["due_date"].startswith("2026-05"), f"Q4 should be May 2026, got {d['due_date']}"


# ============================================================
# Penalty Rules
# ============================================================

class TestGSTPenalty:
    def test_overdue_penalty(self):
        """10 days late at ₹50/day = ₹500."""
        flag = calculate_gst_penalty("GSTR-3B", "2026-03-01", today=date(2026, 3, 11))
        assert flag is not None
        assert flag.impact_amount == 500

    def test_nil_return_penalty(self):
        """10 days late nil return at ₹20/day = ₹200."""
        flag = calculate_gst_penalty("GSTR-3B", "2026-03-01", today=date(2026, 3, 11), is_nil_return=True)
        assert flag is not None
        assert flag.impact_amount == 200
        assert flag.metadata["rate_per_day"] == 20.0

    def test_max_penalty_cap(self):
        """Penalty should cap at ₹5,000 for regular returns."""
        flag = calculate_gst_penalty("GSTR-3B", "2026-01-01", today=date(2026, 12, 31))
        assert flag is not None
        assert flag.impact_amount <= 5000

    def test_nil_return_max_cap(self):
        """Nil return penalty should cap at ₹500."""
        flag = calculate_gst_penalty("GSTR-3B", "2026-01-01", today=date(2026, 12, 31), is_nil_return=True)
        assert flag is not None
        assert flag.impact_amount <= 500

    def test_not_yet_due(self):
        """No penalty if not yet due."""
        flag = calculate_gst_penalty("GSTR-3B", "2026-04-20", today=date(2026, 3, 10))
        assert flag is None


class TestTDSInterest:
    def test_tds_interest_calculation(self):
        """TDS late deposit interest at 1.5% per month."""
        flag = calculate_tds_interest(100000, "2026-01-07", today=date(2026, 3, 10))
        assert flag is not None
        assert flag.impact_amount > 0
        # ~2 months late: 100000 × 1.5% × 3 months (rounded up) = 4500
        assert flag.metadata["months_late"] >= 2

    def test_tds_not_yet_due(self):
        """No interest if not yet due."""
        flag = calculate_tds_interest(100000, "2026-04-07", today=date(2026, 3, 10))
        assert flag is None


# ============================================================
# Rules Engine Integration
# ============================================================

class TestRulesEngine:
    def setup_method(self):
        self.engine = RulesEngine()

    def test_run_all_with_deadlines(self, sample_deadlines):
        result = self.engine.run_all(
            deadlines=sample_deadlines,
            invoices=[],
            today=date(2026, 3, 25),
        )
        assert "flags" in result
        assert "compliance_score" in result
        assert "penalty_risk" in result  # may be "risk_level" depending on key name
        assert isinstance(result["flags"], list)
        # All deadlines are past due by Mar 25, so should have flags
        assert len(result["flags"]) > 0

    def test_run_all_with_invoices(self, sample_deadlines):
        invoices = [
            {"vendor_gstin": "", "invoice_number": "INV-001", "taxable_value": 50000},
            {"vendor_gstin": "27AAACM7890G1Z3", "invoice_number": "INV-001", "taxable_value": 50000},  # duplicate
        ]
        result = self.engine.run_all(
            deadlines=[],
            invoices=invoices,
            today=date(2026, 3, 25),
        )
        assert "flags" in result
        # Should flag missing GSTIN and duplicate
        flag_rules = [f.get("rule_id", "") for f in result["flags"]]
        assert any("gstin" in r.lower() or "missing" in r.lower() for r in flag_rules)

    def test_compliance_score_decreases_with_issues(self, sample_deadlines):
        """More issues should decrease compliance score."""
        clean_result = self.engine.run_all(deadlines=[], invoices=[], today=date(2026, 3, 25))
        messy_result = self.engine.run_all(
            deadlines=sample_deadlines,
            invoices=[{"vendor_gstin": "", "invoice_number": "INV-001"}],
            today=date(2026, 3, 25),
        )
        assert messy_result["compliance_score"] <= clean_result["compliance_score"]

    def test_run_all_empty(self):
        """Empty inputs should return valid result with high compliance score."""
        result = self.engine.run_all(deadlines=[], invoices=[])
        assert result["compliance_score"] == 100
        assert len(result["flags"]) == 0
