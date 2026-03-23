"""
Rules Engine — orchestrates all rule modules and produces a compliance report.

Usage:
    engine = RulesEngine()
    report = engine.run_all(deadlines=deadlines, invoices=invoices)
    # report = {
    #     "flags": [...],
    #     "compliance_score": 85.5,
    #     "penalty_risk": "low",
    #     "total_estimated_penalty": 250.0,
    #     "summary": {...}
    # }

Each rule module is independent:
- deadline_rules: statutory deadline generation + overdue detection
- invoice_rules: invoice-level validation
- penalty_rules: financial impact calculation
"""

import logging
from datetime import date
from typing import List, Optional

from app.services.rules.base import ComplianceFlag, Severity
from app.services.rules import deadline_rules
from app.services.rules import invoice_rules
from app.services.rules import penalty_rules

logger = logging.getLogger(__name__)


class RulesEngine:
    """
    Orchestrates all compliance rule modules.
    Stateless — create a new instance per run.
    """

    def run_all(
        self,
        deadlines: List[dict] = None,
        invoices: List[dict] = None,
        today: date = None,
    ) -> dict:
        """
        Run all rule modules and return a unified compliance report.

        Args:
            deadlines: list of deadline dicts (from DB or generated)
            invoices: list of normalized invoice dicts
            today: override for testing (defaults to date.today())

        Returns:
            {
                "flags": [ComplianceFlag.to_dict(), ...],
                "compliance_score": float (0-100),
                "penalty_risk": "low" | "medium" | "high",
                "total_estimated_penalty": float,
                "summary": {
                    "total_flags": int,
                    "critical": int,
                    "error": int,
                    "warning": int,
                    "info": int,
                    "by_category": {...}
                }
            }
        """
        if today is None:
            today = date.today()

        all_flags: List[ComplianceFlag] = []

        # ---- Module 1: Deadline rules ----
        if deadlines:
            dl_flags = deadline_rules.check_deadlines(deadlines, today)
            all_flags.extend(dl_flags)
            logger.info(f"Deadline rules: {len(dl_flags)} flags")

        # ---- Module 2: Invoice rules ----
        if invoices:
            inv_flags = invoice_rules.check_invoices(invoices)
            all_flags.extend(inv_flags)
            logger.info(f"Invoice rules: {len(inv_flags)} flags")

        # ---- Module 3: Penalty calculation for overdue deadlines ----
        if deadlines:
            for dl in deadlines:
                if dl.get("status") == "completed":
                    continue
                due_str = dl.get("due_date", "")
                dl_type = dl.get("type", "")
                subtype = dl.get("subtype", "")
                amount = dl.get("amount") or 0

                if dl_type == "gst":
                    flag = penalty_rules.calculate_gst_penalty(subtype, due_str, today)
                    if flag:
                        all_flags.append(flag)
                elif dl_type == "tds" and amount > 0:
                    flag = penalty_rules.calculate_tds_interest(amount, due_str, today)
                    if flag:
                        all_flags.append(flag)
                elif dl_type == "roc":
                    flag = penalty_rules.calculate_roc_penalty(subtype, due_str, today)
                    if flag:
                        all_flags.append(flag)

        # ---- Aggregate results ----
        flags_dicts = [f.to_dict() for f in all_flags]

        # Count by severity
        severity_counts = {s.value: 0 for s in Severity}
        for f in all_flags:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

        # Count by category
        category_counts = {}
        for f in all_flags:
            cat = f.category
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Total estimated penalty
        total_penalty = sum(f.impact_amount for f in all_flags if f.impact_amount)

        # Compliance score (100 - deductions)
        compliance_score = self._calculate_score(all_flags, deadlines, invoices)

        # Penalty risk level
        penalty_risk = self._assess_risk(all_flags, total_penalty)

        return {
            "flags": flags_dicts,
            "compliance_score": compliance_score,
            "penalty_risk": penalty_risk,
            "total_estimated_penalty": round(total_penalty, 2),
            "summary": {
                "total_flags": len(all_flags),
                "critical": severity_counts.get(Severity.CRITICAL, 0),
                "error": severity_counts.get(Severity.ERROR, 0),
                "warning": severity_counts.get(Severity.WARNING, 0),
                "info": severity_counts.get(Severity.INFO, 0),
                "by_category": category_counts,
            },
        }

    def check_single_invoice(self, invoice: dict) -> List[dict]:
        """Convenience: run invoice rules on a single invoice."""
        flags = invoice_rules.check_invoices([invoice])
        return [f.to_dict() for f in flags]

    def _calculate_score(
        self,
        flags: List[ComplianceFlag],
        deadlines: Optional[List[dict]],
        invoices: Optional[List[dict]],
    ) -> float:
        """
        Calculate compliance health score (0-100).

        Starts at 100, deducts points per flag severity:
        - CRITICAL: -15 points each
        - ERROR: -8 points each
        - WARNING: -3 points each
        - INFO: -0 points (informational only)

        Floor at 0, ceiling at 100.
        """
        score = 100.0

        deductions = {
            Severity.CRITICAL: 15,
            Severity.ERROR: 8,
            Severity.WARNING: 3,
            Severity.INFO: 0,
        }

        for flag in flags:
            score -= deductions.get(flag.severity, 0)

        return max(0.0, min(100.0, round(score, 1)))

    def _assess_risk(self, flags: List[ComplianceFlag], total_penalty: float) -> str:
        """
        Determine penalty risk level.

        high:   any CRITICAL flag OR total penalty > ₹10,000
        medium: any ERROR flag OR total penalty > ₹1,000
        low:    everything else
        """
        has_critical = any(f.severity == Severity.CRITICAL for f in flags)
        has_error = any(f.severity == Severity.ERROR for f in flags)

        if has_critical or total_penalty > 10000:
            return "high"
        if has_error or total_penalty > 1000:
            return "medium"
        return "low"
