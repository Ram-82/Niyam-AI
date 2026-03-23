"""
Normalization Layer — strict schema enforcement between parser and DB.

Takes raw parser output (per-field dicts with value/confidence/method)
and produces a clean, deterministic NormalizedInvoice ready for the
Rules Engine and database.

Pipeline position:
    OCR → DataParser → **Normalizer** → DB / Rules Engine
"""

import re
import logging
from datetime import datetime
from typing import Optional

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# Confidence threshold — below this, the invoice gets flagged for review
REVIEW_CONFIDENCE_THRESHOLD = 60

# Critical fields — if ANY of these are null, needs_review = True
CRITICAL_FIELDS = ("gstin", "invoice_number", "invoice_date", "total_amount")


class NormalizedInvoice:
    """
    Immutable, validated invoice record.

    Every field is either the correct type or None.
    Never contains wrong data — prefers null over guessing.
    """

    __slots__ = (
        "invoice_id",
        "gstin",
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "taxable_amount",
        "gst_amount",
        "total_amount",
        "cgst",
        "sgst",
        "igst",
        "hsn_codes",
        "confidence_score",
        "needs_review",
        "review_reasons",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def to_dict(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}


# ============================================================
# Amount normalization
# ============================================================

# Strips ₹, Rs, Rs., INR, commas, whitespace
_CURRENCY_STRIP = re.compile(r"[₹,\s]|Rs\.?|INR", re.IGNORECASE)


def _normalize_amount(raw) -> Optional[float]:
    """
    Convert any amount value to a clean float.
    Returns None if unparseable or negative.

    Handles:
      - float/int pass-through
      - strings like "₹6,500.00", "Rs. 12,400", "6500"
      - None → None
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        val = float(raw)
        return round(val, 2) if val >= 0 else None

    if isinstance(raw, str):
        cleaned = _CURRENCY_STRIP.sub("", raw).strip()
        if not cleaned:
            return None
        try:
            val = float(cleaned)
            return round(val, 2) if val >= 0 else None
        except ValueError:
            logger.debug(f"Could not parse amount: {raw!r}")
            return None

    return None


# ============================================================
# Date normalization
# ============================================================

# Ordered by frequency in Indian invoices
_DATE_FORMATS = [
    "%d/%m/%Y",      # 15/03/2026
    "%d-%m-%Y",      # 15-03-2026
    "%d.%m.%Y",      # 15.03.2026
    "%Y-%m-%d",      # 2026-03-15 (ISO — parser already outputs this)
    "%d/%m/%y",      # 15/03/26
    "%d-%m-%y",      # 15-03-26
]


def _normalize_date(raw) -> Optional[str]:
    """
    Convert any date representation to YYYY-MM-DD string.
    Returns None if unparseable or out of sane range (2000–2035).
    """
    if raw is None:
        return None

    if isinstance(raw, datetime):
        if 2000 <= raw.year <= 2035:
            return raw.strftime("%Y-%m-%d")
        return None

    if not isinstance(raw, str):
        return None

    raw = raw.strip()
    if not raw:
        return None

    # If already in ISO format (parser usually outputs this), fast-path
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
            if 2000 <= dt.year <= 2035:
                return raw
        except ValueError:
            pass

    # Try explicit formats
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if 2000 <= dt.year <= 2035:
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Fallback: dateutil (handles "15 March 2026", "Mar 15, 2026", etc.)
    try:
        dt = dateutil_parser.parse(raw, dayfirst=True)
        if 2000 <= dt.year <= 2035:
            return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        pass

    logger.debug(f"Could not parse date: {raw!r}")
    return None


# ============================================================
# GSTIN normalization
# ============================================================

_GSTIN_CLEAN = re.compile(r"[^A-Z0-9]", re.IGNORECASE)
_GSTIN_VALID = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]Z[A-Z0-9]$")


def _normalize_gstin(raw) -> Optional[str]:
    """
    Clean and validate GSTIN. Returns uppercase 15-char string or None.
    """
    if raw is None:
        return None

    if not isinstance(raw, str):
        return None

    cleaned = _GSTIN_CLEAN.sub("", raw).upper().strip()

    if len(cleaned) != 15:
        return None

    # State code check (01–37)
    try:
        state = int(cleaned[:2])
        if state < 1 or state > 37:
            return None
    except ValueError:
        return None

    # Relaxed format check (allow OCR misreads on last chars)
    if not (cleaned[2:7].isalpha() and cleaned[7:11].isdigit() and cleaned[11].isalpha()):
        return None

    return cleaned


# ============================================================
# String normalization
# ============================================================

def _normalize_string(raw) -> Optional[str]:
    """Clean a string field. Returns None if empty after cleaning."""
    if raw is None:
        return None

    if not isinstance(raw, str):
        raw = str(raw)

    cleaned = raw.strip()
    # Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned or len(cleaned) < 2:
        return None

    return cleaned


# ============================================================
# Confidence normalization
# ============================================================

def _normalize_confidence(raw) -> int:
    """Clamp confidence to 0–100 integer."""
    if raw is None:
        return 0
    try:
        val = int(round(float(raw)))
        return max(0, min(100, val))
    except (ValueError, TypeError):
        return 0


# ============================================================
# GST amount reconciliation
# ============================================================

def _reconcile_gst(
    cgst: Optional[float],
    sgst: Optional[float],
    igst: Optional[float],
    gst_amount: Optional[float],
) -> tuple:
    """
    Ensure GST values are consistent. Returns (cgst, sgst, igst, gst_amount).

    Rules:
    1. If CGST+SGST present → gst_amount = cgst + sgst; igst should be 0/null
    2. If IGST present (and no CGST/SGST) → gst_amount = igst
    3. If gst_amount present but no components → keep gst_amount as-is
    4. If components conflict with gst_amount → trust components
    """
    has_intra = (cgst is not None and cgst > 0) or (sgst is not None and sgst > 0)
    has_inter = igst is not None and igst > 0

    if has_intra and has_inter:
        # Conflicting: both intra-state (CGST+SGST) and inter-state (IGST)
        # Trust the larger total — likely the real one
        intra_total = (cgst or 0) + (sgst or 0)
        if intra_total >= igst:
            igst = None
            gst_amount = round(intra_total, 2)
        else:
            cgst = None
            sgst = None
            gst_amount = round(igst, 2)
        logger.warning("Conflicting GST: both CGST/SGST and IGST present. Resolved by larger total.")

    elif has_intra:
        computed = round((cgst or 0) + (sgst or 0), 2)
        if gst_amount is not None and abs(gst_amount - computed) > 1.0:
            # Components disagree with total — trust components
            logger.debug(f"GST mismatch: components={computed}, total={gst_amount}. Trusting components.")
        gst_amount = computed

    elif has_inter:
        gst_amount = round(igst, 2)

    # else: keep gst_amount as-is (may be None)

    return cgst, sgst, igst, gst_amount


# ============================================================
# Total amount cross-check
# ============================================================

def _cross_check_total(
    taxable: Optional[float],
    gst: Optional[float],
    total: Optional[float],
) -> Optional[float]:
    """
    Verify total ≈ taxable + gst. If total is missing but components
    exist, compute it. If total conflicts, return None (unsafe).
    """
    if taxable is not None and gst is not None:
        expected = round(taxable + gst, 2)

        if total is None:
            return expected

        if abs(total - expected) <= 1.0:
            # Close enough — keep original total
            return total

        # Mismatch > ₹1 — don't trust either; return None to force review
        logger.warning(
            f"Total mismatch: total={total}, taxable+gst={expected}. "
            f"Returning None to force review."
        )
        return None

    return total


# ============================================================
# Main normalizer
# ============================================================

def normalize_invoice(parsed: dict, invoice_id: str) -> NormalizedInvoice:
    """
    Takes raw DataParser output and returns a NormalizedInvoice.

    Input format (from DataParser.parse_invoice):
    {
        "gstin":          {"value": "29ABCDE1234F1Z5", "confidence": 80, "method": "..."},
        "invoice_number": {"value": "INV-001",         "confidence": 85, ...},
        "invoice_date":   {"value": "2026-03-15",      "confidence": 88, ...},
        ...
        "overall_confidence": 73,
        "needs_review": [...],
        "extraction_errors": [...]
    }

    Output: NormalizedInvoice with clean types and deterministic review flag.
    """
    review_reasons = list(parsed.get("extraction_errors", []))

    # ---- Extract raw values ----
    def _val(field: str):
        f = parsed.get(field, {})
        if isinstance(f, dict):
            return f.get("value")
        return None

    def _conf(field: str) -> int:
        f = parsed.get(field, {})
        if isinstance(f, dict):
            return _normalize_confidence(f.get("confidence", 0))
        return 0

    # ---- Normalize individual fields ----
    gstin = _normalize_gstin(_val("gstin"))
    invoice_number = _normalize_string(_val("invoice_number"))
    invoice_date = _normalize_date(_val("invoice_date"))
    vendor_name = _normalize_string(_val("vendor_name"))

    taxable_amount = _normalize_amount(_val("taxable_amount"))
    cgst = _normalize_amount(_val("cgst"))
    sgst = _normalize_amount(_val("sgst"))
    igst = _normalize_amount(_val("igst"))
    gst_amount = _normalize_amount(_val("gst_amount"))
    total_amount = _normalize_amount(_val("total_amount"))

    hsn_raw = _val("hsn_codes")
    if isinstance(hsn_raw, list):
        hsn_codes = [str(h) for h in hsn_raw if h]
    else:
        hsn_codes = []

    # ---- GST reconciliation ----
    cgst, sgst, igst, gst_amount = _reconcile_gst(cgst, sgst, igst, gst_amount)

    # ---- Total cross-check ----
    original_total = total_amount
    total_amount = _cross_check_total(taxable_amount, gst_amount, total_amount)

    if original_total is not None and total_amount is None:
        review_reasons.append(
            f"Total amount conflict: stated={original_total}, "
            f"computed={round((taxable_amount or 0) + (gst_amount or 0), 2)}"
        )

    # ---- Confidence score ----
    # Weighted average: critical fields count more
    field_confs = {
        "gstin": (_conf("gstin"), 2),
        "invoice_number": (_conf("invoice_number"), 2),
        "invoice_date": (_conf("invoice_date"), 1.5),
        "total_amount": (_conf("total_amount"), 2),
        "taxable_amount": (_conf("taxable_amount"), 1),
        "cgst": (_conf("cgst"), 0.5),
        "sgst": (_conf("sgst"), 0.5),
        "igst": (_conf("igst"), 0.5),
        "vendor_name": (_conf("vendor_name"), 0.5),
    }

    total_weight = 0.0
    weighted_sum = 0.0
    for field_name, (conf, weight) in field_confs.items():
        # Only include fields that were actually extracted
        val_map = {
            "gstin": gstin, "invoice_number": invoice_number,
            "invoice_date": invoice_date, "total_amount": total_amount,
            "taxable_amount": taxable_amount, "cgst": cgst,
            "sgst": sgst, "igst": igst, "vendor_name": vendor_name,
        }
        if val_map.get(field_name) is not None:
            weighted_sum += conf * weight
            total_weight += weight
        else:
            # Null critical field → penalize
            if field_name in CRITICAL_FIELDS:
                total_weight += weight  # add weight but zero confidence

    confidence_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0.0
    confidence_score = max(0.0, min(100.0, confidence_score))

    # ---- Review flag ----
    needs_review = False

    # Rule 1: overall confidence below threshold
    if confidence_score < REVIEW_CONFIDENCE_THRESHOLD:
        needs_review = True
        review_reasons.append(f"Low confidence: {confidence_score} < {REVIEW_CONFIDENCE_THRESHOLD}")

    # Rule 2: any critical field is null
    critical_vals = {
        "gstin": gstin,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "total_amount": total_amount,
    }
    missing = [k for k, v in critical_vals.items() if v is None]
    if missing:
        needs_review = True
        review_reasons.append(f"Missing critical fields: {', '.join(missing)}")

    # Rule 3: negative or zero total
    if total_amount is not None and total_amount <= 0:
        needs_review = True
        review_reasons.append(f"Invalid total_amount: {total_amount}")
        total_amount = None  # null out bad data

    # Deduplicate reasons
    review_reasons = list(dict.fromkeys(review_reasons))

    return NormalizedInvoice(
        invoice_id=invoice_id,
        gstin=gstin,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        vendor_name=vendor_name,
        taxable_amount=taxable_amount,
        gst_amount=gst_amount,
        total_amount=total_amount,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        hsn_codes=hsn_codes,
        confidence_score=confidence_score,
        needs_review=needs_review,
        review_reasons=review_reasons,
    )
