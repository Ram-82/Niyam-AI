"""
Data Parser — Extract structured invoice data from raw OCR text.

Multi-strategy extraction:
1. Pattern-based: regex for GSTIN, dates, amounts, invoice numbers
2. Keyword-anchored: find value near a label ("Invoice No:", "GSTIN:", "Total")
3. Fallback: alternative patterns, fuzzy matching, null with low confidence

Every field returns: { "value": ..., "confidence": 0-100 }
"""

import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# GSTIN Patterns
# Format: 2-digit state + 10-char PAN + 1 entity + 1 Z + 1 checksum
# Example: 29ABCDE1234F1Z5
# ============================================================
GSTIN_STRICT = re.compile(
    r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][Z][A-Z\d])\b"
)
# Looser pattern: handles OCR errors (O→0, I→1, Z→2, etc.)
GSTIN_LOOSE = re.compile(
    r"\b(\d{2}[A-Z0-9]{5}\d{4}[A-Z0-9]\d[A-Z0-9][Z2][A-Z0-9])\b"
)

# ============================================================
# Invoice Number Patterns
# Common formats: INV-001, INV/2026/001, GST/001, #001, No. 001
# ============================================================
INVOICE_NUM_PATTERNS = [
    # Explicit label: "Invoice No: XYZ-123" or "Invoice Number: XYZ-123"
    re.compile(
        r"(?:Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\-/\.]{2,25})",
        re.IGNORECASE,
    ),
    # "Bill No: XYZ"
    re.compile(
        r"(?:Bill\s*(?:No\.?|Number)\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\-/\.]{2,25})",
        re.IGNORECASE,
    ),
    # Standalone pattern: INV-2026-001, GST/001/2026
    re.compile(
        r"\b((?:INV|GST|BILL|TAX|SI|PI)[/\-][\w\-/]{3,20})\b",
        re.IGNORECASE,
    ),
]

# ============================================================
# Date Patterns — Indian formats first
# ============================================================
DATE_PATTERNS = [
    # dd/mm/yyyy or dd-mm-yyyy or dd.mm.yyyy
    (re.compile(r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})\b"), "%d-%m-%Y"),
    (re.compile(r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})\b"), "%d.%m.%Y"),
    # dd Month yyyy (e.g., 15 June 2025, 15 Jun 2025)
    (re.compile(
        r"\b(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
        r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})\b",
        re.IGNORECASE,
    ), None),
    # yyyy-mm-dd (ISO)
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), "%Y-%m-%d"),
]

# Labels that appear near invoice dates
DATE_KEYWORDS = [
    "invoice date", "inv date", "date of invoice",
    "bill date", "dated", "date:",
    "tax invoice date", "document date",
]

# ============================================================
# Amount Patterns — ₹ and Rs. prefixed, comma-separated numbers
# ============================================================
AMOUNT_PATTERN = re.compile(
    r"[₹Rs\.]*\s*([\d,]+\.?\d{0,2})\b"
)
# Strict: requires at least one digit, optional commas, optional decimals
AMOUNT_STRICT = re.compile(
    r"\b(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)\b"
)

# Keywords for different amount fields
TOTAL_KEYWORDS = [
    "grand total", "total amount", "net amount", "total payable",
    "amount payable", "invoice total", "bill total", "total value",
    "total amt", "amount due",
]
TAXABLE_KEYWORDS = [
    "taxable value", "taxable amount", "assessable value",
    "base amount", "subtotal", "sub total", "sub-total",
    "total taxable", "value of supply",
]
CGST_KEYWORDS = ["cgst", "central gst", "central tax"]
SGST_KEYWORDS = ["sgst", "state gst", "state tax", "utgst"]
IGST_KEYWORDS = ["igst", "integrated gst", "integrated tax"]
GST_TOTAL_KEYWORDS = [
    "total tax", "gst amount", "total gst", "tax amount",
    "gst total",
]

# ============================================================
# Vendor/Supplier Name Keywords
# ============================================================
VENDOR_KEYWORDS = [
    "sold by", "seller", "supplier", "vendor", "from:",
    "billed by", "consignor", "ship from",
    "name of supplier", "supplier name",
]


class ExtractedField:
    """A single extracted field with confidence."""

    __slots__ = ("value", "confidence", "method")

    def __init__(self, value, confidence: int, method: str = ""):
        self.value = value
        self.confidence = confidence
        self.method = method

    def to_dict(self) -> dict:
        d = {"value": self.value, "confidence": self.confidence}
        if self.method:
            d["method"] = self.method
        return d

    def __repr__(self):
        return f"ExtractedField({self.value!r}, conf={self.confidence})"


def _none_field() -> ExtractedField:
    return ExtractedField(None, 0, "not_found")


class DataParser:
    """
    Multi-strategy invoice parser.
    Takes raw OCR text, returns structured invoice data with per-field confidence.
    """

    def parse_invoice(self, raw_text: str) -> dict:
        """
        Main entry point. Returns normalized invoice JSON.

        Example output:
        {
            "gstin": {"value": "29ABCDE1234F1Z5", "confidence": 92},
            "invoice_number": {"value": "INV-2026-042", "confidence": 85},
            "invoice_date": {"value": "2026-03-15", "confidence": 78},
            "vendor_name": {"value": "Office Supplies Inc.", "confidence": 45},
            "taxable_amount": {"value": 3600.00, "confidence": 70},
            "cgst": {"value": 324.00, "confidence": 65},
            "sgst": {"value": 324.00, "confidence": 65},
            "igst": {"value": 0, "confidence": 50},
            "gst_amount": {"value": 648.00, "confidence": 68},
            "total_amount": {"value": 4248.00, "confidence": 75},
            "hsn_codes": {"value": ["8471"], "confidence": 60},
            "overall_confidence": 67,
            "needs_review": ["vendor_name", "igst"],
            "extraction_errors": []
        }
        """
        if not raw_text or not raw_text.strip():
            return self._empty_result("Empty text provided")

        text = raw_text.strip()
        errors = []

        # Extract each field
        gstin = self._extract_gstin(text)
        invoice_number = self._extract_invoice_number(text)
        invoice_date = self._extract_invoice_date(text)
        vendor_name = self._extract_vendor_name(text)
        taxable_amount = self._extract_amount(text, TAXABLE_KEYWORDS, "taxable_amount")
        cgst = self._extract_amount(text, CGST_KEYWORDS, "cgst")
        sgst = self._extract_amount(text, SGST_KEYWORDS, "sgst")
        igst = self._extract_amount(text, IGST_KEYWORDS, "igst")
        gst_amount = self._extract_amount(text, GST_TOTAL_KEYWORDS, "gst_amount")
        total_amount = self._extract_amount(text, TOTAL_KEYWORDS, "total_amount")
        hsn_codes = self._extract_hsn_codes(text)

        # ---- Cross-field validation & confidence adjustments ----

        # If we have CGST+SGST but no gst_amount, compute it
        if gst_amount.value is None and cgst.value is not None and sgst.value is not None:
            computed = round(cgst.value + sgst.value, 2)
            gst_amount = ExtractedField(computed, min(cgst.confidence, sgst.confidence) - 5, "computed")

        # If we have IGST but no CGST/SGST, gst_amount = IGST
        if gst_amount.value is None and igst.value is not None and igst.value > 0:
            gst_amount = ExtractedField(igst.value, igst.confidence - 5, "computed")

        # If we have taxable + gst but no total, compute it
        if total_amount.value is None and taxable_amount.value is not None and gst_amount.value is not None:
            computed = round(taxable_amount.value + gst_amount.value, 2)
            total_amount = ExtractedField(computed, min(taxable_amount.confidence, gst_amount.confidence) - 10, "computed")

        # If total exists but taxable doesn't, and gst exists, back-calculate
        if taxable_amount.value is None and total_amount.value is not None and gst_amount.value is not None:
            computed = round(total_amount.value - gst_amount.value, 2)
            if computed > 0:
                taxable_amount = ExtractedField(computed, min(total_amount.confidence, gst_amount.confidence) - 10, "computed")

        # Validate: total ≈ taxable + gst
        if (total_amount.value and taxable_amount.value and gst_amount.value):
            expected = round(taxable_amount.value + gst_amount.value, 2)
            diff = abs(total_amount.value - expected)
            if diff > 1.0:
                errors.append(f"Amount mismatch: total={total_amount.value}, taxable+gst={expected}, diff={diff}")
                # Lower confidence on total
                total_amount = ExtractedField(total_amount.value, max(total_amount.confidence - 15, 10), total_amount.method)

        # Build result
        fields = {
            "gstin": gstin,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "vendor_name": vendor_name,
            "taxable_amount": taxable_amount,
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst,
            "gst_amount": gst_amount,
            "total_amount": total_amount,
            "hsn_codes": hsn_codes,
        }

        # Calculate overall confidence
        confidences = [f.confidence for f in fields.values() if f.value is not None]
        overall = round(sum(confidences) / len(confidences)) if confidences else 0

        # Fields that need manual review (confidence < 50 or value is None for important fields)
        important_fields = ["gstin", "invoice_number", "invoice_date", "total_amount"]
        needs_review = []
        for name in important_fields:
            field = fields[name]
            if field.value is None or field.confidence < 50:
                needs_review.append(name)

        result = {k: v.to_dict() for k, v in fields.items()}
        result["overall_confidence"] = overall
        result["needs_review"] = needs_review
        result["extraction_errors"] = errors

        return result

    # ================================================================
    # GSTIN Extraction
    # ================================================================
    def _extract_gstin(self, text: str) -> ExtractedField:
        """
        Strategy 1: Regex strict pattern
        Strategy 2: Keyword-anchored ("GSTIN:" followed by pattern)
        Strategy 3: Loose pattern with OCR error tolerance
        """
        # Strategy 1: strict regex across entire text
        match = GSTIN_STRICT.search(text)
        if match:
            gstin = match.group(1)
            if self._validate_gstin_checksum(gstin):
                return ExtractedField(gstin, 95, "regex_strict")
            return ExtractedField(gstin, 85, "regex_strict_no_checksum")

        # Strategy 2: keyword-anchored
        for keyword in ["gstin", "gst no", "gst number", "gst in", "gstn"]:
            pattern = re.compile(
                rf"{keyword}\s*[:\-]?\s*(\d{{2}}[A-Z0-9]{{10}}[A-Z0-9]{{3}})",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if match:
                gstin = match.group(1).upper()
                conf = 80 if self._validate_gstin_checksum(gstin) else 65
                return ExtractedField(gstin, conf, "keyword_anchored")

        # Strategy 3: loose regex (handles OCR misreads)
        match = GSTIN_LOOSE.search(text)
        if match:
            gstin = match.group(1).upper()
            return ExtractedField(gstin, 55, "regex_loose")

        return _none_field()

    def _validate_gstin_checksum(self, gstin: str) -> bool:
        """Validate GSTIN structure (not full checksum, but format)."""
        if not gstin or len(gstin) != 15:
            return False
        try:
            state_code = int(gstin[:2])
            if state_code < 1 or state_code > 37:
                return False
            # PAN part: chars 2-11
            pan = gstin[2:12]
            if not (pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()):
                return False
            # 13th char must be Z (or close to it for OCR tolerance)
            if gstin[13] not in ("Z", "2"):  # '2' is common OCR misread of 'Z'
                return False
            return True
        except (ValueError, IndexError):
            return False

    # ================================================================
    # Invoice Number Extraction
    # ================================================================
    def _extract_invoice_number(self, text: str) -> ExtractedField:
        """
        Strategy 1: Keyword-anchored patterns
        Strategy 2: Standalone format patterns
        """
        for pattern in INVOICE_NUM_PATTERNS[:2]:  # keyword-anchored first
            match = pattern.search(text)
            if match:
                inv_no = match.group(1).strip().rstrip(".")
                if len(inv_no) >= 3:
                    return ExtractedField(inv_no, 85, "keyword_anchored")

        # Strategy 2: standalone patterns
        match = INVOICE_NUM_PATTERNS[2].search(text)
        if match:
            inv_no = match.group(1).strip()
            return ExtractedField(inv_no, 60, "pattern_standalone")

        # Strategy 3: look for "No." or "#" followed by alphanumeric
        fallback = re.search(
            r"(?:No\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,20})",
            text, re.IGNORECASE,
        )
        if fallback:
            return ExtractedField(fallback.group(1).strip(), 40, "fallback")

        return _none_field()

    # ================================================================
    # Date Extraction
    # ================================================================
    def _extract_invoice_date(self, text: str) -> ExtractedField:
        """
        Strategy 1: Keyword-anchored date near "Invoice Date:", "Dated:", etc.
        Strategy 2: First date found in text
        Strategy 3: Parse named months (15 June 2025)
        """
        text_lower = text.lower()

        # Strategy 1: keyword-anchored
        for keyword in DATE_KEYWORDS:
            pos = text_lower.find(keyword)
            if pos >= 0:
                # Search in the ~60 chars after the keyword
                window = text[pos:pos + 80]
                date_val = self._find_date_in_window(window)
                if date_val:
                    return ExtractedField(date_val, 88, "keyword_anchored")

        # Strategy 2: first valid date in text
        all_dates = self._find_all_dates(text)
        if all_dates:
            return ExtractedField(all_dates[0], 55, "first_found")

        return _none_field()

    def _find_date_in_window(self, window: str) -> Optional[str]:
        """Try to parse a date from a text window."""
        for pattern, fmt in DATE_PATTERNS:
            match = pattern.search(window)
            if match:
                raw = match.group(1)
                parsed = self._try_parse_date(raw, fmt)
                if parsed:
                    return parsed
        return None

    def _find_all_dates(self, text: str) -> list:
        """Find all parseable dates in text."""
        dates = []
        for pattern, fmt in DATE_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(1)
                parsed = self._try_parse_date(raw, fmt)
                if parsed:
                    dates.append(parsed)
        return dates

    def _try_parse_date(self, raw: str, fmt: Optional[str]) -> Optional[str]:
        """Try to parse a date string into ISO format (YYYY-MM-DD)."""
        # Normalize separators for fmt-based parsing
        normalized = raw.replace("-", "/").replace(".", "/")

        if fmt:
            fmt_normalized = fmt.replace("-", "/").replace(".", "/")
            try:
                dt = datetime.strptime(normalized, fmt_normalized)
                # Sanity check: year between 2000 and 2035
                if 2000 <= dt.year <= 2035:
                    return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
        else:
            # Named month: "15 June 2025"
            from dateutil import parser as dateutil_parser
            try:
                dt = dateutil_parser.parse(raw, dayfirst=True)
                if 2000 <= dt.year <= 2035:
                    return dt.strftime("%Y-%m-%d")
            except (ValueError, OverflowError):
                pass

        return None

    # ================================================================
    # Amount Extraction
    # ================================================================
    def _extract_amount(self, text: str, keywords: list, field_name: str) -> ExtractedField:
        """
        Strategy 1: Keyword-anchored — find amount near keyword
        Strategy 2: Pattern search near keyword line
        """
        text_lower = text.lower()
        lines = text.split("\n")

        # Strategy 1: keyword-anchored (search same line and next line)
        for keyword in keywords:
            for i, line in enumerate(lines):
                if keyword in line.lower():
                    # Search this line and the next for an amount
                    search_zone = line
                    if i + 1 < len(lines):
                        search_zone += " " + lines[i + 1]

                    amount = self._find_largest_amount_in_text(search_zone, keyword)
                    if amount is not None:
                        return ExtractedField(amount, 75, "keyword_anchored")

        # Strategy 2: search near keyword position in raw text
        for keyword in keywords:
            pos = text_lower.find(keyword)
            if pos >= 0:
                window = text[pos:pos + 100]
                amounts = self._find_all_amounts(window)
                if amounts:
                    return ExtractedField(amounts[-1], 55, "keyword_window")

        return ExtractedField(None, 0, "not_found")

    def _find_largest_amount_in_text(self, text: str, keyword: str) -> Optional[float]:
        """Find the amount value closest to the keyword, skipping percentages."""
        text_lower = text.lower()
        kw_pos = text_lower.find(keyword.lower())
        if kw_pos >= 0:
            after_keyword = text[kw_pos + len(keyword):]
        else:
            after_keyword = text

        amounts = self._find_all_amounts(after_keyword)
        if amounts:
            return amounts[0]
        return None

    def _find_all_amounts(self, text: str) -> list:
        """Find all numeric amounts in text, skipping percentages. Returns list of floats."""
        amounts = []
        for match in AMOUNT_STRICT.finditer(text):
            raw = match.group(1).replace(",", "")
            # Skip if followed by % (it's a percentage, not an amount)
            end_pos = match.end()
            remaining = text[end_pos:end_pos + 3].strip()
            if remaining.startswith("%"):
                continue
            try:
                val = float(raw)
                if val > 0:
                    amounts.append(round(val, 2))
            except ValueError:
                continue
        return amounts

    # ================================================================
    # Vendor Name Extraction
    # ================================================================
    def _extract_vendor_name(self, text: str) -> ExtractedField:
        """
        Strategy 1: Keyword-anchored ("Sold by:", "Supplier:", etc.)
        Strategy 2: First non-empty line that looks like a company name (fallback)
        """
        text_lower = text.lower()
        lines = text.split("\n")

        # Strategy 1: keyword-anchored
        for keyword in VENDOR_KEYWORDS:
            pos = text_lower.find(keyword)
            if pos >= 0:
                after = text[pos + len(keyword):].strip()
                # Take text until next newline or colon
                name_match = re.match(r"[:\-]?\s*(.+?)(?:\n|$)", after)
                if name_match:
                    name = name_match.group(1).strip().strip(":")
                    if 3 <= len(name) <= 100:
                        return ExtractedField(name, 65, "keyword_anchored")

        # Strategy 2: first line that looks like a business name
        # (contains "Ltd", "Pvt", "Inc", "Enterprises", "Trading", etc.)
        biz_patterns = re.compile(
            r".*(Pvt|Ltd|Private|Limited|Inc|Corp|LLP|Enterprises|"
            r"Trading|Industries|Solutions|Services|Company).*",
            re.IGNORECASE,
        )
        for line in lines[:15]:  # Only check first 15 lines
            line = line.strip()
            if biz_patterns.match(line) and len(line) >= 5:
                return ExtractedField(line, 40, "pattern_match")

        return _none_field()

    # ================================================================
    # HSN Code Extraction
    # ================================================================
    def _extract_hsn_codes(self, text: str) -> ExtractedField:
        """
        HSN codes are 4, 6, or 8 digit numbers.
        Strategy 1: keyword-anchored near "HSN" or "SAC"
        Strategy 2: find 4-8 digit numbers near "HSN"
        """
        text_lower = text.lower()
        codes = set()
        confidence = 0

        # Strategy 1: keyword-anchored
        for keyword in ["hsn", "sac", "hsn/sac", "hsn code", "sac code"]:
            pos = text_lower.find(keyword)
            if pos >= 0:
                window = text[pos:pos + 200]
                # Find 4-8 digit numbers
                for match in re.finditer(r"\b(\d{4,8})\b", window):
                    code = match.group(1)
                    if self._is_valid_hsn(code):
                        codes.add(code)
                        confidence = max(confidence, 70)

        # Strategy 2: look in table rows for 4-8 digit numbers
        if not codes:
            for match in re.finditer(r"\b(\d{4})\b", text):
                code = match.group(1)
                # Only include 4-digit codes that look like HSN (not years, not amounts)
                if self._is_valid_hsn(code) and not self._looks_like_year(code):
                    codes.add(code)
                    confidence = max(confidence, 35)

        if codes:
            return ExtractedField(sorted(codes), confidence, "pattern")
        return ExtractedField([], 0, "not_found")

    def _is_valid_hsn(self, code: str) -> bool:
        """Basic HSN validation — must be 4, 6, or 8 digits."""
        if len(code) not in (4, 6, 8):
            return False
        if code.startswith("0000"):
            return False
        return True

    def _looks_like_year(self, code: str) -> bool:
        """Check if a 4-digit code is likely a year, not an HSN."""
        try:
            val = int(code)
            return 1990 <= val <= 2040
        except ValueError:
            return False

    # ================================================================
    # Empty result
    # ================================================================
    def _empty_result(self, error: str = "") -> dict:
        fields = [
            "gstin", "invoice_number", "invoice_date", "vendor_name",
            "taxable_amount", "cgst", "sgst", "igst", "gst_amount",
            "total_amount", "hsn_codes",
        ]
        result = {f: {"value": None, "confidence": 0} for f in fields}
        result["overall_confidence"] = 0
        result["needs_review"] = fields[:4]
        result["extraction_errors"] = [error] if error else []
        return result
