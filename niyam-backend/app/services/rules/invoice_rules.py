"""
Invoice Rules — validate individual invoices and detect anomalies.

Runs on normalized invoices (post-normalization layer).
Uses review_reasons codes from the normalizer as input signals.
"""

from typing import List

from app.services.rules.base import ComplianceFlag, Severity, FlagCategory
from app.services.normalization import ReviewCode


def check_invoices(invoices: List[dict]) -> List[ComplianceFlag]:
    """
    Validate a batch of invoices. Returns ComplianceFlag for each issue.

    Input: list of normalized invoice dicts (from NormalizedInvoice.to_dict()
           or from DB records with the same field names).
    """
    flags = []

    seen_numbers = {}  # invoice_number → invoice_id (duplicate detection)

    for inv in invoices:
        inv_id = inv.get("invoice_id") or inv.get("id", "unknown")
        inv_date = inv.get("invoice_date")
        review_reasons = inv.get("review_reasons") or []

        # If review_reasons is a comma-separated string (from DB), split it
        if isinstance(review_reasons, str):
            review_reasons = [r.strip() for r in review_reasons.split(",") if r.strip()]

        # ---- Rule 1: Missing GSTIN ----
        if ReviewCode.MISSING_GSTIN in review_reasons or inv.get("gstin") is None:
            flags.append(ComplianceFlag(
                rule_id="invoice_missing_gstin",
                category=FlagCategory.INVOICE,
                severity=Severity.ERROR,
                message="Invoice missing vendor GSTIN — ITC cannot be claimed",
                action_required="Obtain valid GSTIN from vendor before claiming ITC",
                impact_amount=_estimate_itc_at_risk(inv),
                due_date=inv_date,
                related_id=inv_id,
                metadata={"vendor_name": inv.get("vendor_name")},
            ))

        # ---- Rule 2: Invalid GSTIN format ----
        elif ReviewCode.INVALID_GSTIN_FORMAT in review_reasons:
            flags.append(ComplianceFlag(
                rule_id="invoice_invalid_gstin",
                category=FlagCategory.INVOICE,
                severity=Severity.WARNING,
                message="GSTIN format invalid — verify manually",
                action_required="Cross-check GSTIN on GST portal and correct the invoice",
                due_date=inv_date,
                related_id=inv_id,
                metadata={"vendor_name": inv.get("vendor_name")},
            ))

        # ---- Rule 3: Missing total amount ----
        if ReviewCode.MISSING_TOTAL_AMOUNT in review_reasons or (
            inv.get("total_amount") is None or inv.get("total_amount") == 0
        ):
            flags.append(ComplianceFlag(
                rule_id="invoice_missing_total",
                category=FlagCategory.INVOICE,
                severity=Severity.WARNING,
                message="Invoice total amount missing or zero",
                action_required="Re-upload invoice or manually enter the total amount",
                due_date=inv_date,
                related_id=inv_id,
            ))

        # ---- Rule 4: Total mismatch (normalizer detected) ----
        if ReviewCode.TOTAL_MISMATCH in review_reasons:
            flags.append(ComplianceFlag(
                rule_id="invoice_total_mismatch",
                category=FlagCategory.INVOICE,
                severity=Severity.ERROR,
                message="Invoice total does not match taxable + GST",
                action_required="Verify invoice amounts — total should equal taxable value + GST",
                due_date=inv_date,
                related_id=inv_id,
            ))

        # ---- Rule 5: GST conflict (both CGST/SGST and IGST) ----
        if ReviewCode.GST_CONFLICT in review_reasons:
            flags.append(ComplianceFlag(
                rule_id="invoice_gst_conflict",
                category=FlagCategory.INVOICE,
                severity=Severity.WARNING,
                message="Invoice has both intra-state and inter-state GST — auto-resolved, verify",
                action_required="Confirm whether this is an intra-state or inter-state supply",
                due_date=inv_date,
                related_id=inv_id,
            ))

        # ---- Rule 6: Low confidence extraction ----
        confidence = inv.get("confidence_score") or inv.get("confidence") or 0
        if ReviewCode.LOW_CONFIDENCE in review_reasons or confidence < 50:
            flags.append(ComplianceFlag(
                rule_id="invoice_low_confidence",
                category=FlagCategory.INVOICE,
                severity=Severity.INFO,
                message=f"OCR extraction confidence is low ({confidence}%) — manual review recommended",
                action_required="Review extracted data against the original invoice",
                due_date=inv_date,
                related_id=inv_id,
                metadata={"confidence": confidence},
            ))

        # ---- Rule 7: Duplicate invoice number ----
        inv_number = inv.get("invoice_number")
        vendor_gstin = inv.get("gstin") or inv.get("vendor_gstin")
        if inv_number:
            dup_key = f"{vendor_gstin or ''}::{inv_number}"
            if dup_key in seen_numbers:
                flags.append(ComplianceFlag(
                    rule_id="invoice_duplicate",
                    category=FlagCategory.INVOICE,
                    severity=Severity.ERROR,
                    message=f"Duplicate invoice {inv_number} from same vendor",
                    action_required="Verify this is not a duplicate entry — remove if duplicate",
                    due_date=inv_date,
                    related_id=inv_id,
                    metadata={
                        "duplicate_of": seen_numbers[dup_key],
                        "invoice_number": inv_number,
                    },
                ))
            else:
                seen_numbers[dup_key] = inv_id

        # ---- Rule 8: Missing invoice date ----
        if inv.get("invoice_date") is None:
            flags.append(ComplianceFlag(
                rule_id="invoice_missing_date",
                category=FlagCategory.INVOICE,
                severity=Severity.WARNING,
                message="Invoice date missing — cannot determine filing period",
                action_required="Add invoice date to determine the correct GST filing period",
                related_id=inv_id,
            ))

    return flags


def _estimate_itc_at_risk(inv: dict) -> float:
    """
    Estimate the ITC amount at risk if GSTIN is missing.
    ITC = CGST + SGST + IGST (or gst_amount).
    """
    gst = inv.get("gst_amount") or 0
    if gst > 0:
        return float(gst)

    cgst = inv.get("cgst") or 0
    sgst = inv.get("sgst") or 0
    igst = inv.get("igst") or 0
    total_tax = cgst + sgst + igst
    return float(total_tax) if total_tax > 0 else 0.0
