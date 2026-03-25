"""
GST Compliance Validator — invoice-level legal validation.

Sits between extraction and storage/dashboard.
Takes structured invoice data, validates against real GST rules,
and outputs compliance status with financial impact.

Pipeline position:
    OCR → Parser → AI Fallback → **GST Validator** → DB / Dashboard

Every rule is:
    1. Grounded in actual GST law (referenced in comments)
    2. Deterministic (no AI, no guessing)
    3. Explainable (tells user WHY it matters and WHAT to do)
"""

import re
import logging
from datetime import date, datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================
# Valid Indian State Codes for GSTIN (01-37 + 97 for other territory)
# Ref: CBIC notification, Schedule 1 of CGST Act
# ============================================================
VALID_STATE_CODES = set(range(1, 38)) | {97}

# Standard GST rates in India (%)
STANDARD_GST_RATES = {0, 0.25, 3, 5, 12, 18, 28}

# GST late filing penalty: ₹50/day (₹25 CGST + ₹25 SGST), max ₹10,000
# Ref: Section 47 of CGST Act 2017
GST_LATE_FEE_PER_DAY = 50
GST_LATE_FEE_MAX = 10000

# ITC claim time limit: invoice must be < 1 year old on filing date
# Ref: Section 16(4) of CGST Act 2017 (as amended)
ITC_CLAIM_MONTHS_LIMIT = 12


# ============================================================
# Individual Rule Functions
# ============================================================

def validate_gstin_format(gstin: str) -> Dict:
    """
    Rule: GSTIN must be valid 15-character format.
    Ref: Rule 10 of CGST Rules 2017

    Format: SS PPPPP NNNN P E Z C
      SS     = State code (01-37, 97)
      PPPPP  = First 5 chars of PAN (alpha)
      NNNN   = Next 4 digits of PAN
      P      = PAN check letter (alpha)
      E      = Entity code (1-9, A-Z)
      Z      = Fixed 'Z'
      C      = Checksum (alpha or digit)
    """
    if not gstin:
        return {
            "type": "GSTIN_MISSING",
            "severity": "high",
            "message": "Vendor GSTIN is missing",
            "impact": "ITC cannot be claimed without valid supplier GSTIN (Section 16(2)(aa) CGST Act)",
            "itc_blocked": True,
        }

    gstin = gstin.strip().upper()

    if len(gstin) != 15:
        return {
            "type": "GSTIN_INVALID_LENGTH",
            "severity": "high",
            "message": f"GSTIN has {len(gstin)} characters (must be 15)",
            "impact": "ITC cannot be claimed — invalid GSTIN",
            "itc_blocked": True,
        }

    # State code check
    try:
        state_code = int(gstin[:2])
    except ValueError:
        return {
            "type": "GSTIN_INVALID_STATE",
            "severity": "high",
            "message": f"GSTIN state code '{gstin[:2]}' is not numeric",
            "impact": "ITC cannot be claimed — GSTIN state code invalid",
            "itc_blocked": True,
        }

    if state_code not in VALID_STATE_CODES:
        return {
            "type": "GSTIN_INVALID_STATE",
            "severity": "high",
            "message": f"GSTIN state code {state_code:02d} is not a valid Indian state/UT code",
            "impact": "ITC cannot be claimed — GSTIN state code does not exist",
            "itc_blocked": True,
        }

    # PAN structure: chars 2-6 alpha, 7-10 digits, 11 alpha
    pan = gstin[2:12]
    if not (pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()):
        return {
            "type": "GSTIN_INVALID_PAN",
            "severity": "high",
            "message": "GSTIN contains invalid PAN structure (chars 3-12)",
            "impact": "ITC cannot be claimed — embedded PAN is malformed",
            "itc_blocked": True,
        }

    # Entity code (position 13): must be alphanumeric
    if not gstin[12].isalnum():
        return {
            "type": "GSTIN_INVALID_FORMAT",
            "severity": "medium",
            "message": "GSTIN entity code (position 13) is invalid",
            "impact": "GSTIN may be OCR-misread — verify against GST portal",
            "itc_blocked": False,
        }

    # Position 14 must be 'Z'
    if gstin[13] != "Z":
        return {
            "type": "GSTIN_INVALID_FORMAT",
            "severity": "medium",
            "message": f"GSTIN position 14 is '{gstin[13]}' (must be 'Z')",
            "impact": "Likely OCR error — verify GSTIN against GST portal",
            "itc_blocked": False,
        }

    # Checksum (position 15): alphanumeric
    if not gstin[14].isalnum():
        return {
            "type": "GSTIN_INVALID_CHECKSUM",
            "severity": "medium",
            "message": "GSTIN checksum character is invalid",
            "impact": "Verify GSTIN on GST portal (may be OCR error)",
            "itc_blocked": False,
        }

    return None  # Valid


def validate_gst_structure(gst_breakdown: Dict) -> Optional[Dict]:
    """
    Rule: GST must be either intra-state (CGST+SGST) or inter-state (IGST), not both.
    Ref: Section 9 (CGST Act) and Section 5 (IGST Act)

    Intra-state supply: CGST + SGST (equal amounts)
    Inter-state supply: IGST only
    """
    cgst = gst_breakdown.get("cgst", 0) or 0
    sgst = gst_breakdown.get("sgst", 0) or 0
    igst = gst_breakdown.get("igst", 0) or 0

    has_intra = cgst > 0 or sgst > 0
    has_inter = igst > 0

    if has_intra and has_inter:
        return {
            "type": "GST_STRUCTURE_INVALID",
            "severity": "high",
            "message": "Invoice has both CGST/SGST and IGST — violates GST Act",
            "impact": (
                "Section 9 CGST Act: intra-state supply attracts CGST+SGST. "
                "Section 5 IGST Act: inter-state supply attracts IGST. "
                "Both cannot apply simultaneously. ITC eligibility uncertain."
            ),
            "itc_blocked": False,
        }

    # CGST and SGST should be equal (same rate applied to state + centre)
    if has_intra and cgst > 0 and sgst > 0:
        if abs(cgst - sgst) > max(1.0, cgst * 0.05):
            return {
                "type": "CGST_SGST_UNEQUAL",
                "severity": "medium",
                "message": f"CGST (₹{cgst:,.2f}) and SGST (₹{sgst:,.2f}) should be equal",
                "impact": "Under GST, CGST and SGST rates are always equal — verify amounts",
                "itc_blocked": False,
            }

    return None


def validate_tax_calculation(taxable_value: float, gst_breakdown: Dict) -> Optional[Dict]:
    """
    Rule: GST amount should match taxable value × GST rate.
    Ref: Section 15 of CGST Act 2017 (value of supply)

    We detect the effective rate and check if amounts are consistent.
    Tolerance: ±2% of expected GST (handles rounding across line items).
    """
    if not taxable_value or taxable_value <= 0:
        return None  # Can't validate without taxable value

    cgst = gst_breakdown.get("cgst", 0) or 0
    sgst = gst_breakdown.get("sgst", 0) or 0
    igst = gst_breakdown.get("igst", 0) or 0
    gst_total = cgst + sgst + igst

    if gst_total <= 0:
        return None  # Zero-rated or exempt — valid

    # Detect effective rate
    effective_rate = (gst_total / taxable_value) * 100

    # Check if rate is close to a standard rate
    closest_rate = min(STANDARD_GST_RATES - {0}, key=lambda r: abs(r - effective_rate), default=None)

    if closest_rate is None:
        return None

    # Calculate expected GST at closest standard rate
    expected_gst = taxable_value * (closest_rate / 100)
    tolerance = max(2.0, expected_gst * 0.02)  # ±2% or ₹2, whichever is higher

    if abs(gst_total - expected_gst) > tolerance:
        return {
            "type": "GST_AMOUNT_MISMATCH",
            "severity": "medium",
            "message": (
                f"GST amount ₹{gst_total:,.2f} doesn't match expected "
                f"₹{expected_gst:,.2f} at {closest_rate}% on ₹{taxable_value:,.2f}"
            ),
            "impact": (
                "Tax calculation error — may lead to ITC mismatch during GSTR-2B reconciliation. "
                "Verify with vendor or check for multiple GST rate items."
            ),
            "itc_blocked": False,
        }

    return None


def validate_total_amount(total_amount: float, taxable_value: float, gst_breakdown: Dict) -> Optional[Dict]:
    """
    Rule: Total = Taxable Value + GST
    Ref: Section 33 of CGST Act (amount of tax to be indicated in invoice)

    Tolerance: ±₹1 or ±0.5% of total, whichever is higher.
    """
    if not total_amount or total_amount <= 0:
        return {
            "type": "TOTAL_MISSING",
            "severity": "medium",
            "message": "Invoice total amount is missing or zero",
            "impact": "Cannot verify invoice completeness — review manually",
            "itc_blocked": False,
        }

    if not taxable_value or taxable_value <= 0:
        return None  # Can't cross-check without taxable value

    cgst = gst_breakdown.get("cgst", 0) or 0
    sgst = gst_breakdown.get("sgst", 0) or 0
    igst = gst_breakdown.get("igst", 0) or 0
    gst_total = cgst + sgst + igst

    expected = taxable_value + gst_total
    tolerance = max(1.0, total_amount * 0.005)  # ±₹1 or 0.5%

    if abs(total_amount - expected) > tolerance:
        diff = total_amount - expected
        return {
            "type": "TOTAL_MISMATCH",
            "severity": "high" if abs(diff) > total_amount * 0.05 else "medium",
            "message": (
                f"Total ₹{total_amount:,.2f} ≠ Taxable ₹{taxable_value:,.2f} + GST ₹{gst_total:,.2f} "
                f"(expected ₹{expected:,.2f}, diff ₹{diff:+,.2f})"
            ),
            "impact": (
                "Invoice arithmetic error — Section 31 CGST Act requires accurate invoicing. "
                "Mismatch will cause GSTR-2B reconciliation failure."
            ),
            "itc_blocked": False,
        }

    return None


def validate_invoice_date(invoice_date: str) -> Optional[Dict]:
    """
    Rule: Invoice date must be valid, not in future, and within ITC claim window.
    Ref: Section 16(4) CGST Act — ITC must be claimed within specified time limit.

    Time limit: ITC for a financial year must be claimed by the earlier of:
    - 30th November of the following financial year, OR
    - Date of filing annual return (GSTR-9)
    """
    if not invoice_date:
        return {
            "type": "DATE_MISSING",
            "severity": "medium",
            "message": "Invoice date is missing",
            "impact": "Cannot determine filing period or ITC claim deadline",
            "itc_blocked": False,
        }

    try:
        inv_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return {
            "type": "DATE_INVALID",
            "severity": "medium",
            "message": f"Invoice date '{invoice_date}' is not a valid date",
            "impact": "Cannot determine filing period",
            "itc_blocked": False,
        }

    today = date.today()

    # Future date
    if inv_date > today:
        return {
            "type": "DATE_FUTURE",
            "severity": "high",
            "message": f"Invoice date {invoice_date} is in the future",
            "impact": "Future-dated invoices are invalid — verify date with vendor",
            "itc_blocked": True,
        }

    # ITC time limit: >12 months old
    days_old = (today - inv_date).days
    if days_old > ITC_CLAIM_MONTHS_LIMIT * 30:
        months_old = days_old // 30
        return {
            "type": "DATE_ITC_EXPIRED",
            "severity": "high",
            "message": f"Invoice is {months_old} months old — ITC claim window may have expired",
            "impact": (
                f"Section 16(4) CGST Act: ITC for FY invoices must be claimed by 30 Nov "
                f"of the next FY. Invoice dated {invoice_date} ({months_old} months ago) "
                f"may be beyond the claim window. Verify filing deadline."
            ),
            "itc_blocked": False,  # Not definitively blocked — depends on FY
        }

    # Very recent: warn if < 2 days (might not be in GSTR-2B yet)
    if days_old < 2:
        return {
            "type": "DATE_VERY_RECENT",
            "severity": "low",
            "message": "Invoice is very recent — may not appear in GSTR-2B yet",
            "impact": "Allow 2-3 days for vendor's GSTR-1 filing to reflect in your GSTR-2B",
            "itc_blocked": False,
        }

    return None


def validate_itc_eligibility(
    gstin_valid: bool,
    gst_total: float,
    invoice_complete: bool,
    date_issue: Optional[Dict],
) -> Dict:
    """
    Rule: ITC eligibility requires ALL conditions.
    Ref: Section 16(2) of CGST Act 2017

    Conditions for ITC:
    (a) Registered person possesses tax invoice
    (b) Goods/services received
    (c) Tax actually paid to government
    (d) Furnishing of return
    (aa) Supplier has furnished return (GSTR-1) — reflected in GSTR-2B
    """
    itc_amount = gst_total
    reasons = []

    if not gstin_valid:
        reasons.append("Invalid/missing supplier GSTIN (Section 16(2)(a))")
        itc_amount = 0

    if gst_total <= 0:
        reasons.append("No GST charged on invoice (exempt or zero-rated)")
        itc_amount = 0

    if not invoice_complete:
        reasons.append("Invoice is incomplete — missing critical fields (Section 31)")

    if date_issue and date_issue.get("type") == "DATE_FUTURE":
        reasons.append("Future-dated invoice is invalid")
        itc_amount = 0

    if date_issue and date_issue.get("type") == "DATE_ITC_EXPIRED":
        reasons.append("ITC claim window may have expired (Section 16(4))")

    eligible = len(reasons) == 0 and itc_amount > 0

    return {
        "eligible": eligible,
        "itc_amount": round(itc_amount, 2),
        "itc_at_risk": round(itc_amount, 2) if not eligible and itc_amount > 0 else 0,
        "reasons": reasons if reasons else ["All conditions met — ITC claimable"],
    }


def validate_line_items(line_items: List[Dict], taxable_value: float) -> Optional[Dict]:
    """
    Rule: Sum of line item amounts should approximate taxable value.
    Ref: Rule 46 of CGST Rules — invoice must contain description, quantity, value.
    """
    if not line_items:
        return None  # No items to validate

    items_total = sum(item.get("amount", 0) for item in line_items)
    if items_total <= 0:
        return None

    if taxable_value and taxable_value > 0:
        tolerance = max(1.0, taxable_value * 0.05)  # 5% tolerance
        if abs(items_total - taxable_value) > tolerance:
            return {
                "type": "LINE_ITEMS_TOTAL_MISMATCH",
                "severity": "low",
                "message": (
                    f"Line items sum ₹{items_total:,.2f} ≠ taxable value ₹{taxable_value:,.2f} "
                    f"(diff ₹{abs(items_total - taxable_value):,.2f})"
                ),
                "impact": "May include additional charges (freight, discount) not in line items",
                "itc_blocked": False,
            }

    return None


# ============================================================
# Main Validator
# ============================================================

def validate_invoice(data: dict) -> dict:
    """
    Run all GST compliance validations on extracted invoice data.

    Args:
        data: Output from InvoiceProcessor.process() — the full result dict

    Returns:
        {
            "is_valid": bool,
            "compliance_score": 0-100,
            "issues": [
                {
                    "type": "GSTIN_INVALID",
                    "severity": "high|medium|low",
                    "message": "...",
                    "impact": "..."
                }
            ],
            "financial_risk": {
                "itc_eligible": bool,
                "itc_amount": float,
                "itc_at_risk": float,
                "penalty_estimate": float
            },
            "itc_eligibility": {
                "eligible": bool,
                "itc_amount": float,
                "reasons": [...]
            },
            "summary": "One-line summary of compliance status"
        }
    """
    issues = []
    gstin = data.get("vendor_gstin", "")
    invoice_date = data.get("invoice_date", "")
    total_amount = data.get("total_amount", 0)
    taxable_value = data.get("taxable_value", 0)
    gst_breakdown = data.get("gst_breakdown", {})
    line_items = data.get("line_items", [])

    cgst = gst_breakdown.get("cgst", 0) or 0
    sgst = gst_breakdown.get("sgst", 0) or 0
    igst = gst_breakdown.get("igst", 0) or 0
    gst_total = cgst + sgst + igst

    # ---- Rule 1: GSTIN Validation ----
    gstin_issue = validate_gstin_format(gstin)
    gstin_valid = gstin_issue is None
    if gstin_issue:
        issues.append(gstin_issue)

    # ---- Rule 2: GST Structure ----
    structure_issue = validate_gst_structure(gst_breakdown)
    if structure_issue:
        issues.append(structure_issue)

    # ---- Rule 3: Tax Calculation ----
    tax_calc_issue = validate_tax_calculation(taxable_value, gst_breakdown)
    if tax_calc_issue:
        issues.append(tax_calc_issue)

    # ---- Rule 4: Total Amount ----
    total_issue = validate_total_amount(total_amount, taxable_value, gst_breakdown)
    if total_issue:
        issues.append(total_issue)

    # ---- Rule 5: Invoice Date ----
    date_issue = validate_invoice_date(invoice_date)
    if date_issue:
        issues.append(date_issue)

    # ---- Rule 6: Line Items ----
    line_issue = validate_line_items(line_items, taxable_value)
    if line_issue:
        issues.append(line_issue)

    # ---- Rule 7: Invoice Completeness ----
    missing_fields = []
    if not gstin:
        missing_fields.append("vendor_gstin")
    if not data.get("invoice_number"):
        missing_fields.append("invoice_number")
    if not invoice_date:
        missing_fields.append("invoice_date")
    if not total_amount:
        missing_fields.append("total_amount")

    invoice_complete = len(missing_fields) == 0

    if missing_fields:
        issues.append({
            "type": "INVOICE_INCOMPLETE",
            "severity": "medium",
            "message": f"Missing required fields: {', '.join(missing_fields)}",
            "impact": (
                "Rule 46 of CGST Rules requires: supplier name/GSTIN, invoice number, "
                "date, description, value, and tax amount. Incomplete invoices may not "
                "qualify for ITC."
            ),
            "itc_blocked": False,
        })

    # ---- Rule 8: ITC Eligibility ----
    itc_result = validate_itc_eligibility(gstin_valid, gst_total, invoice_complete, date_issue)

    # ---- Compliance Score ----
    score = 100
    severity_deductions = {"high": 30, "medium": 15, "low": 5}
    for issue in issues:
        sev = issue.get("severity", "low")
        score -= severity_deductions.get(sev, 0)
    score = max(0, min(100, score))

    # ---- Penalty Estimate ----
    penalty_estimate = 0.0
    high_issues = [i for i in issues if i.get("severity") == "high"]
    if high_issues:
        # Rough estimate: ₹50/day for 10 days (if filing is delayed due to issues)
        penalty_estimate = GST_LATE_FEE_PER_DAY * 10

    # ---- Financial Risk ----
    financial_risk = {
        "itc_eligible": itc_result["eligible"],
        "itc_amount": itc_result["itc_amount"],
        "itc_at_risk": itc_result["itc_at_risk"],
        "penalty_estimate": penalty_estimate,
    }

    # ---- Summary ----
    if not issues:
        summary = "Invoice is GST-compliant — all validations passed"
    else:
        high_count = len([i for i in issues if i["severity"] == "high"])
        med_count = len([i for i in issues if i["severity"] == "medium"])
        parts = []
        if high_count:
            parts.append(f"{high_count} critical issue(s)")
        if med_count:
            parts.append(f"{med_count} warning(s)")
        if itc_result["itc_at_risk"] > 0:
            parts.append(f"₹{itc_result['itc_at_risk']:,.2f} ITC at risk")
        summary = "Invoice has " + ", ".join(parts) if parts else "Invoice has minor issues"

    return {
        "is_valid": len(issues) == 0,
        "compliance_score": score,
        "issues": issues,
        "financial_risk": financial_risk,
        "itc_eligibility": itc_result,
        "summary": summary,
    }
