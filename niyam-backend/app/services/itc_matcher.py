"""
ITC Matcher — core matching logic for purchase invoices vs GSTR-2B.

Deterministic, no ML. Every invoice gets classified into exactly one
MatchType with financial impact calculated to the rupee.

Pipeline position:
    Invoices (DB) + GSTR-2B (upload) → **ITC Matcher** → ITC Service
"""

import logging
import re
from enum import Enum
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Match Types
# ============================================================

class MatchType(str, Enum):
    """Every invoice-2B pair resolves to exactly one of these."""
    EXACT_MATCH = "exact_match"              # Perfect match — ITC claimable
    PARTIAL_MATCH = "partial_match"          # Amounts differ within tolerance
    MISSING_IN_2B = "missing_in_2b"          # In books but NOT in GSTR-2B
    MISSING_IN_INVOICES = "missing_in_invoices"  # In 2B but NOT in books
    DUPLICATE_CLAIM = "duplicate_claim"      # Same invoice claimed more than once


# ============================================================
# Configuration
# ============================================================

class MatchConfig:
    """Configurable matching parameters."""
    __slots__ = (
        "amount_tolerance",       # ₹ tolerance for taxable amount matching
        "gst_tolerance",          # ₹ tolerance for GST amount matching
        "fuzzy_invoice_number",   # enable normalized invoice number comparison
    )

    def __init__(
        self,
        amount_tolerance: float = 1.0,
        gst_tolerance: float = 1.0,
        fuzzy_invoice_number: bool = True,
    ):
        self.amount_tolerance = amount_tolerance
        self.gst_tolerance = gst_tolerance
        self.fuzzy_invoice_number = fuzzy_invoice_number


DEFAULT_CONFIG = MatchConfig()


# ============================================================
# Invoice number normalization (for fuzzy matching)
# ============================================================

# Strip common prefixes/suffixes, collapse separators, uppercase
_INV_STRIP = re.compile(r"[^A-Z0-9]", re.IGNORECASE)


def _normalize_inv_number(raw: Optional[str]) -> str:
    """
    Normalize invoice number for comparison.
    "INV/2026/0342" → "INV20260342"
    "GST-INV-0342" → "GSTINV0342"
    """
    if not raw:
        return ""
    return _INV_STRIP.sub("", raw).upper()


# ============================================================
# Match Result
# ============================================================

# ============================================================
# Severity mapping — aligns with Rules Engine severity system
# ============================================================

_MATCH_SEVERITY = {
    MatchType.EXACT_MATCH: "none",
    MatchType.PARTIAL_MATCH: "medium",
    MatchType.MISSING_IN_2B: "high",
    MatchType.MISSING_IN_INVOICES: "low",
    MatchType.DUPLICATE_CLAIM: "critical",
}

_MATCH_ACTION_TYPE = {
    MatchType.EXACT_MATCH: "monitor",
    MatchType.PARTIAL_MATCH: "fix",
    MatchType.MISSING_IN_2B: "recover",
    MatchType.MISSING_IN_INVOICES: "recover",
    MatchType.DUPLICATE_CLAIM: "remove",
}


def _calculate_recovery_priority(
    match_type: str,
    itc_amount: float,
    invoice_date: str,
) -> str:
    """
    Determine recovery priority for actionable ITC items.

    High:   recent (≤30 days) AND ≥₹5,000
    Medium: recent OR ≥₹1,000
    Low:    old AND small
    None:   EXACT_MATCH (nothing to recover)
    """
    if match_type == MatchType.EXACT_MATCH:
        return "none"

    is_recent = False
    if invoice_date:
        try:
            from datetime import date as _date
            inv_d = _date.fromisoformat(str(invoice_date)[:10])
            is_recent = (_date.today() - inv_d).days <= 30
        except (ValueError, TypeError):
            pass

    high_value = itc_amount >= 5000
    mid_value = itc_amount >= 1000

    if is_recent and high_value:
        return "high"
    if is_recent or mid_value:
        return "medium"
    return "low"


class MatchResult:
    """Result of matching a single invoice against GSTR-2B."""

    __slots__ = (
        "invoice_id",
        "gstr2b_id",
        "match_type",
        "severity",           # none, low, medium, high, critical
        "vendor_gstin",
        "invoice_number",
        "eligible_itc",       # max ITC available (from 2B or invoice, whichever lower)
        "claimed_itc",        # ITC actually claimable after matching
        "itc_at_risk",        # ITC that may be denied
        "recovery_priority",  # none, low, medium, high
        "action_type",        # recover, fix, remove, monitor
        "risk_flag",          # True if any risk
        "reason",             # structured reason code
        "confidence_score",   # 0-100
        "action_required",    # what user should do
        "due_date",           # relevant deadline
        "metadata",           # extra context
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))
        # Auto-compute severity, action_type, recovery_priority from match_type
        if self.severity is None and self.match_type is not None:
            self.severity = _MATCH_SEVERITY.get(self.match_type, "none")
        if self.action_type is None and self.match_type is not None:
            self.action_type = _MATCH_ACTION_TYPE.get(self.match_type, "monitor")
        if self.recovery_priority is None and self.match_type is not None:
            itc = float(self.itc_at_risk or 0) + float(self.eligible_itc or 0) if self.match_type == MatchType.MISSING_IN_INVOICES else float(self.itc_at_risk or 0)
            self.recovery_priority = _calculate_recovery_priority(
                self.match_type, itc, self.due_date,
            )

    def to_dict(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}


# ============================================================
# Core Matcher
# ============================================================

class ITCMatcher:
    """
    Matches purchase invoices against GSTR-2B entries.

    Deterministic logic only. No ML, no guessing.
    Every decision traceable to a specific rule.
    """

    def __init__(self, config: MatchConfig = None):
        self.config = config or DEFAULT_CONFIG

    def match(
        self,
        invoices: List[dict],
        gstr2b_entries: List[dict],
    ) -> List[MatchResult]:
        """
        Match invoices against GSTR-2B entries.

        Args:
            invoices: normalized purchase invoices from DB
            gstr2b_entries: parsed GSTR-2B invoice entries

        Returns:
            List of MatchResult — one per invoice + one per unmatched 2B entry
        """
        results: List[MatchResult] = []

        # ---- Build 2B lookup index ----
        # Key: (gstin, normalized_invoice_number) → list of 2B entries
        index_2b = self._build_2b_index(gstr2b_entries)

        # Track which 2B entries got matched (to find MISSING_IN_INVOICES)
        matched_2b_ids = set()

        # Track invoice numbers per vendor (to detect DUPLICATE_CLAIM)
        seen_invoices: Dict[str, str] = {}  # "gstin::inv_number" → invoice_id

        for inv in invoices:
            inv_id = inv.get("invoice_id") or inv.get("id", "unknown")
            gstin = (inv.get("vendor_gstin") or inv.get("gstin") or "").upper().strip()
            inv_number_raw = inv.get("invoice_number") or ""
            inv_number_norm = _normalize_inv_number(inv_number_raw)
            inv_date = inv.get("invoice_date")

            # GST amounts from invoice
            inv_taxable = float(inv.get("taxable_value") or inv.get("taxable_amount") or 0)
            inv_cgst = float(inv.get("cgst") or 0)
            inv_sgst = float(inv.get("sgst") or 0)
            inv_igst = float(inv.get("igst") or 0)
            inv_gst = inv_cgst + inv_sgst + inv_igst
            if inv_gst == 0:
                inv_gst = float(inv.get("gst_amount") or 0)

            # ---- Check for duplicate claim ----
            dup_key = f"{gstin}::{inv_number_norm}"
            if dup_key in seen_invoices and inv_number_norm:
                results.append(MatchResult(
                    invoice_id=inv_id,
                    gstr2b_id=None,
                    match_type=MatchType.DUPLICATE_CLAIM,
                    vendor_gstin=gstin,
                    invoice_number=inv_number_raw,
                    eligible_itc=inv_gst,
                    claimed_itc=0,
                    itc_at_risk=inv_gst,
                    risk_flag=True,
                    reason="duplicate_invoice_same_vendor",
                    confidence_score=95,
                    action_required="Remove duplicate ITC claim — this invoice already exists",
                    due_date=inv_date,
                    metadata={
                        "duplicate_of": seen_invoices[dup_key],
                        "original_invoice_id": seen_invoices[dup_key],
                    },
                ))
                continue
            if inv_number_norm:
                seen_invoices[dup_key] = inv_id

            # ---- Try to find match in 2B ----
            entry_2b = self._find_2b_match(gstin, inv_number_norm, index_2b)

            if entry_2b is None:
                # MISSING_IN_2B — vendor hasn't filed, ITC at risk
                results.append(MatchResult(
                    invoice_id=inv_id,
                    gstr2b_id=None,
                    match_type=MatchType.MISSING_IN_2B,
                    vendor_gstin=gstin,
                    invoice_number=inv_number_raw,
                    eligible_itc=inv_gst,
                    claimed_itc=0,
                    itc_at_risk=inv_gst,
                    risk_flag=True,
                    reason="invoice_not_in_gstr2b",
                    confidence_score=90,
                    action_required=(
                        "Contact vendor to file GSTR-1 so invoice reflects in 2B"
                        if gstin else "Obtain vendor GSTIN first — ITC cannot be claimed without it"
                    ),
                    due_date=inv_date,
                    metadata={"vendor_name": inv.get("vendor_name")},
                ))
                continue

            # Mark 2B entry as matched
            entry_2b_id = entry_2b.get("_2b_id", "")
            matched_2b_ids.add(entry_2b_id)

            # ---- Compare amounts ----
            b2_taxable = float(entry_2b.get("taxable_value") or entry_2b.get("taxval") or 0)
            b2_cgst = float(entry_2b.get("cgst") or entry_2b.get("camt") or 0)
            b2_sgst = float(entry_2b.get("sgst") or entry_2b.get("samt") or 0)
            b2_igst = float(entry_2b.get("igst") or entry_2b.get("iamt") or 0)
            b2_gst = b2_cgst + b2_sgst + b2_igst

            taxable_diff = abs(inv_taxable - b2_taxable)
            gst_diff = abs(inv_gst - b2_gst)

            if (taxable_diff <= self.config.amount_tolerance and
                    gst_diff <= self.config.gst_tolerance):
                # EXACT_MATCH
                itc = min(inv_gst, b2_gst)  # conservative: claim the lower
                results.append(MatchResult(
                    invoice_id=inv_id,
                    gstr2b_id=entry_2b_id,
                    match_type=MatchType.EXACT_MATCH,
                    vendor_gstin=gstin,
                    invoice_number=inv_number_raw,
                    eligible_itc=b2_gst,
                    claimed_itc=itc,
                    itc_at_risk=0,
                    risk_flag=False,
                    reason="matched",
                    confidence_score=100,
                    action_required=None,
                    due_date=inv_date,
                    metadata={
                        "taxable_diff": round(taxable_diff, 2),
                        "gst_diff": round(gst_diff, 2),
                    },
                ))

            else:
                # PARTIAL_MATCH — amounts differ
                # Claimable ITC = the LOWER of invoice vs 2B (conservative)
                itc_claimable = min(inv_gst, b2_gst)
                itc_at_risk = abs(inv_gst - b2_gst)

                reason = self._partial_reason(inv_taxable, b2_taxable, inv_gst, b2_gst)

                results.append(MatchResult(
                    invoice_id=inv_id,
                    gstr2b_id=entry_2b_id,
                    match_type=MatchType.PARTIAL_MATCH,
                    vendor_gstin=gstin,
                    invoice_number=inv_number_raw,
                    eligible_itc=b2_gst,
                    claimed_itc=itc_claimable,
                    itc_at_risk=itc_at_risk,
                    risk_flag=True,
                    reason=reason,
                    confidence_score=self._partial_confidence(taxable_diff, gst_diff, inv_taxable),
                    action_required=self._partial_action(reason, inv_taxable, b2_taxable, inv_gst, b2_gst),
                    due_date=inv_date,
                    metadata={
                        "invoice_taxable": inv_taxable,
                        "gstr2b_taxable": b2_taxable,
                        "invoice_gst": round(inv_gst, 2),
                        "gstr2b_gst": round(b2_gst, 2),
                        "taxable_diff": round(taxable_diff, 2),
                        "gst_diff": round(gst_diff, 2),
                    },
                ))

        # ---- Find MISSING_IN_INVOICES (in 2B but not in books) ----
        for entry in gstr2b_entries:
            entry_id = entry.get("_2b_id", "")
            if entry_id in matched_2b_ids:
                continue

            gstin_2b = (entry.get("gstin") or entry.get("ctin") or "").upper().strip()
            inv_num_2b = entry.get("invoice_number") or entry.get("inum") or ""
            b2_cgst = float(entry.get("cgst") or entry.get("camt") or 0)
            b2_sgst = float(entry.get("sgst") or entry.get("samt") or 0)
            b2_igst = float(entry.get("igst") or entry.get("iamt") or 0)
            b2_gst = b2_cgst + b2_sgst + b2_igst
            inv_date_2b = entry.get("invoice_date") or entry.get("idt")

            results.append(MatchResult(
                invoice_id=None,
                gstr2b_id=entry_id,
                match_type=MatchType.MISSING_IN_INVOICES,
                vendor_gstin=gstin_2b,
                invoice_number=inv_num_2b,
                eligible_itc=b2_gst,
                claimed_itc=0,
                itc_at_risk=0,
                risk_flag=True,
                reason="in_2b_but_not_in_books",
                confidence_score=85,
                action_required="Record this purchase invoice in your books to claim ITC",
                due_date=inv_date_2b,
                metadata={"recoverable_itc": b2_gst},
            ))

        return results

    # ---- Internal helpers ----

    def _build_2b_index(self, entries: List[dict]) -> Dict[str, List[dict]]:
        """
        Build lookup index from GSTR-2B entries.
        Key: "GSTIN::NORMALIZED_INV_NUM"
        Also index by GSTIN alone for fallback matching.
        """
        index = {}
        for i, entry in enumerate(entries):
            # Assign internal ID for tracking
            entry["_2b_id"] = entry.get("_2b_id", f"2b_{i}")

            gstin = (entry.get("gstin") or entry.get("ctin") or "").upper().strip()
            inv_num = entry.get("invoice_number") or entry.get("inum") or ""
            inv_num_norm = _normalize_inv_number(inv_num)

            # Primary key: GSTIN + invoice number
            key = f"{gstin}::{inv_num_norm}"
            index.setdefault(key, []).append(entry)

            # Secondary key: GSTIN only (for amount-based fallback)
            gstin_key = f"{gstin}::*"
            index.setdefault(gstin_key, []).append(entry)

        return index

    def _find_2b_match(
        self,
        gstin: str,
        inv_number_norm: str,
        index: Dict[str, List[dict]],
    ) -> Optional[dict]:
        """
        Find matching 2B entry. Priority:
        1. Exact GSTIN + exact invoice number
        2. Exact GSTIN + fuzzy invoice number (if enabled)
        """
        # Priority 1: exact key
        key = f"{gstin}::{inv_number_norm}"
        matches = index.get(key, [])
        if matches:
            return matches[0]  # first match wins

        # Priority 2: same GSTIN, check all entries for fuzzy inv number
        if self.config.fuzzy_invoice_number and inv_number_norm:
            gstin_entries = index.get(f"{gstin}::*", [])
            for entry in gstin_entries:
                entry_inv = _normalize_inv_number(
                    entry.get("invoice_number") or entry.get("inum") or ""
                )
                # Check if one contains the other (handles prefix/suffix differences)
                if entry_inv and inv_number_norm and (
                    inv_number_norm in entry_inv or entry_inv in inv_number_norm
                ):
                    return entry

        return None

    def _partial_reason(
        self,
        inv_taxable: float,
        b2_taxable: float,
        inv_gst: float,
        b2_gst: float,
    ) -> str:
        """Determine the specific reason for partial match."""
        taxable_diff = abs(inv_taxable - b2_taxable)
        gst_diff = abs(inv_gst - b2_gst)

        if taxable_diff > self.config.amount_tolerance and gst_diff > self.config.gst_tolerance:
            return "taxable_and_gst_mismatch"
        if taxable_diff > self.config.amount_tolerance:
            return "taxable_amount_mismatch"
        return "gst_amount_mismatch"

    def _partial_confidence(
        self,
        taxable_diff: float,
        gst_diff: float,
        inv_taxable: float,
    ) -> int:
        """
        Calculate confidence for partial match.
        Small differences → higher confidence (likely rounding).
        Large differences → lower confidence (likely wrong invoice).
        """
        if inv_taxable == 0:
            return 50

        pct_diff = (taxable_diff / inv_taxable) * 100

        if pct_diff <= 0.5:
            return 90   # rounding difference
        if pct_diff <= 2:
            return 75   # minor discrepancy
        if pct_diff <= 5:
            return 60   # moderate — needs review
        if pct_diff <= 10:
            return 45   # significant — likely error
        return 30       # major mismatch

    def _partial_action(
        self,
        reason: str,
        inv_taxable: float,
        b2_taxable: float,
        inv_gst: float,
        b2_gst: float,
    ) -> str:
        """Generate specific action for partial match."""
        if reason == "taxable_amount_mismatch":
            diff = round(inv_taxable - b2_taxable, 2)
            direction = "higher" if diff > 0 else "lower"
            return (
                f"Taxable amount is ₹{abs(diff):,.2f} {direction} than GSTR-2B — "
                f"correct invoice amount or ask vendor to amend GSTR-1"
            )
        if reason == "gst_amount_mismatch":
            diff = round(inv_gst - b2_gst, 2)
            direction = "higher" if diff > 0 else "lower"
            return (
                f"GST amount is ₹{abs(diff):,.2f} {direction} than GSTR-2B — "
                f"verify tax rate and amounts with vendor"
            )
        # Both mismatch
        return (
            f"Both taxable (₹{abs(inv_taxable - b2_taxable):,.2f}) and GST "
            f"(₹{abs(inv_gst - b2_gst):,.2f}) differ from GSTR-2B — "
            f"reconcile with vendor before claiming ITC"
        )
