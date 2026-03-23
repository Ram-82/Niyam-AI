"""
Vendor Insights — per-GSTIN reliability scoring.

Tracks vendor behaviour across ITC matching runs:
- How often do their invoices match 2B?
- How often are they missing from 2B?
- How often do amounts mismatch?

Output: reliability_score (0-100) per vendor GSTIN.

This is not stored long-term yet (MVP) — calculated per matching run.
Future: persist to DB for trending over time.
"""

import logging
from typing import List, Dict

from app.services.itc_matcher import MatchType

logger = logging.getLogger(__name__)


class VendorScore:
    """Reliability score for a single vendor GSTIN."""

    __slots__ = (
        "vendor_gstin",
        "vendor_name",
        "total_invoices",
        "exact_matches",
        "partial_matches",
        "missing_in_2b",
        "duplicates",
        "total_itc_value",
        "itc_at_risk",
        "reliability_score",
    )

    def __init__(self, vendor_gstin: str, vendor_name: str = None):
        self.vendor_gstin = vendor_gstin
        self.vendor_name = vendor_name
        self.total_invoices = 0
        self.exact_matches = 0
        self.partial_matches = 0
        self.missing_in_2b = 0
        self.duplicates = 0
        self.total_itc_value = 0.0
        self.itc_at_risk = 0.0
        self.reliability_score = 0

    def to_dict(self) -> dict:
        return {
            "vendor_gstin": self.vendor_gstin,
            "vendor_name": self.vendor_name,
            "total_invoices": self.total_invoices,
            "exact_matches": self.exact_matches,
            "partial_matches": self.partial_matches,
            "missing_in_2b": self.missing_in_2b,
            "duplicates": self.duplicates,
            "total_itc_value": round(self.total_itc_value, 2),
            "itc_at_risk": round(self.itc_at_risk, 2),
            "reliability_score": self.reliability_score,
        }


def calculate_vendor_scores(match_results: List[dict]) -> List[VendorScore]:
    """
    Calculate reliability scores for all vendors in a matching run.

    Scoring formula:
        base = (exact_matches / total_invoices) × 100
        partial_penalty = partial_matches × 5  (each partial = -5)
        missing_penalty = missing_in_2b × 15   (each missing = -15)
        duplicate_penalty = duplicates × 25     (each duplicate = -25)
        score = max(0, base - partial_penalty - missing_penalty - duplicate_penalty)

    This means:
        - 100% exact match → score = 100
        - 1 missing out of 10 → score ~= 75
        - All missing → score = 0
        - Any duplicates → heavy penalty
    """
    # Group results by vendor GSTIN
    vendors: Dict[str, VendorScore] = {}

    for result in match_results:
        gstin = result.get("vendor_gstin") or ""
        if not gstin:
            continue

        match_type = result.get("match_type", "")

        # Skip MISSING_IN_INVOICES — those are 2B-only, no vendor issue
        if match_type == MatchType.MISSING_IN_INVOICES:
            continue

        if gstin not in vendors:
            vendors[gstin] = VendorScore(
                vendor_gstin=gstin,
                vendor_name=result.get("metadata", {}).get("vendor_name"),
            )

        vs = vendors[gstin]
        vs.total_invoices += 1
        vs.total_itc_value += float(result.get("eligible_itc") or 0)
        vs.itc_at_risk += float(result.get("itc_at_risk") or 0)

        if match_type == MatchType.EXACT_MATCH:
            vs.exact_matches += 1
        elif match_type == MatchType.PARTIAL_MATCH:
            vs.partial_matches += 1
        elif match_type == MatchType.MISSING_IN_2B:
            vs.missing_in_2b += 1
        elif match_type == MatchType.DUPLICATE_CLAIM:
            vs.duplicates += 1

    # Calculate scores
    scored = []
    for vs in vendors.values():
        if vs.total_invoices == 0:
            vs.reliability_score = 0
        else:
            base = (vs.exact_matches / vs.total_invoices) * 100
            partial_penalty = vs.partial_matches * 5
            missing_penalty = vs.missing_in_2b * 15
            duplicate_penalty = vs.duplicates * 25

            score = base - partial_penalty - missing_penalty - duplicate_penalty
            vs.reliability_score = max(0, min(100, round(score)))

        scored.append(vs)

    # Sort: worst vendors first (most actionable)
    scored.sort(key=lambda v: v.reliability_score)

    return scored
