"""
Invoice Processor — unified pipeline for document → structured invoice data.

Single entry point: process(file_path, mime_type) → InvoiceResult

Pipeline:
    File → OCR (with retry) → Layout Analysis → Hybrid Extraction → Validation → Result

This module orchestrates the existing OCR, parser, and normalizer layers,
adding layout-aware line item extraction, per-field confidence, and flags.
"""

import logging
import re
from typing import List, Dict, Optional, Tuple

from app.services.ocr_service import OCRService
from app.services.data_parser import DataParser, ExtractedField, _none_field
from app.services.data_parser import (
    GSTIN_STRICT, GSTIN_LOOSE,
    TOTAL_KEYWORDS, TAXABLE_KEYWORDS,
    CGST_KEYWORDS, SGST_KEYWORDS, IGST_KEYWORDS, GST_TOTAL_KEYWORDS,
    AMOUNT_STRICT,
)
from app.services.ai_extractor import AIExtractor, should_trigger_ai, merge_results

logger = logging.getLogger(__name__)

# ============================================================
# Line Item Extraction
# ============================================================

# Column header patterns for invoice tables
_QTY_HEADERS = re.compile(r"(?:qty|quantity|nos|units|pcs)", re.IGNORECASE)
_RATE_HEADERS = re.compile(r"(?:rate|price|unit\s*price|mrp)", re.IGNORECASE)
_AMT_HEADERS = re.compile(r"(?:amount|amt|total|value)", re.IGNORECASE)
_DESC_HEADERS = re.compile(r"(?:description|particulars|item|product|goods|service|desc)", re.IGNORECASE)
_HSN_HEADERS = re.compile(r"(?:hsn|sac|hsn/sac)", re.IGNORECASE)


def _identify_column_roles(headers: List[str]) -> Dict[str, int]:
    """
    Map table column headers to semantic roles.
    Returns: {"description": col_idx, "quantity": col_idx, "rate": col_idx, "amount": col_idx, ...}
    """
    roles = {}
    for i, header in enumerate(headers):
        h = header.strip()
        if not h:
            continue
        if _DESC_HEADERS.search(h) and "description" not in roles:
            roles["description"] = i
        elif _QTY_HEADERS.search(h) and "quantity" not in roles:
            roles["quantity"] = i
        elif _RATE_HEADERS.search(h) and "rate" not in roles:
            roles["rate"] = i
        elif _AMT_HEADERS.search(h) and "amount" not in roles:
            roles["amount"] = i
        elif _HSN_HEADERS.search(h) and "hsn" not in roles:
            roles["hsn"] = i
    return roles


def _parse_number(raw: str) -> Optional[float]:
    """Parse a number from a table cell, handling Indian number formats."""
    if not raw:
        return None
    cleaned = re.sub(r"[₹Rs.,\s]", "", raw.strip())
    # Re-add decimal point if removed
    # Handle "1234.56" vs "1,234.56"
    if "." not in cleaned and "." in raw:
        # Find original decimal position
        parts = raw.strip().replace(",", "").split(".")
        if len(parts) == 2:
            cleaned = parts[0].replace(" ", "") + "." + parts[1].strip()
    try:
        val = float(cleaned) if cleaned else None
        return val if val is not None and val >= 0 else None
    except (ValueError, TypeError):
        return None


def extract_line_items_from_tables(tables: List[dict]) -> Tuple[List[dict], int]:
    """
    Extract structured line items from OCR-detected tables.

    Args:
        tables: List of table dicts with "headers" and "rows"

    Returns:
        (line_items, confidence)
        line_items: [{"description": ..., "quantity": ..., "rate": ..., "amount": ..., "hsn": ...}]
        confidence: 0-100
    """
    all_items = []
    best_confidence = 0

    for table in tables:
        headers = table.get("headers", [])
        rows = table.get("rows", [])

        if not headers or not rows:
            continue

        roles = _identify_column_roles(headers)

        # Need at least description or amount to be useful
        if "description" not in roles and "amount" not in roles:
            continue

        confidence = 0
        if "description" in roles:
            confidence += 30
        if "amount" in roles:
            confidence += 30
        if "quantity" in roles:
            confidence += 20
        if "rate" in roles:
            confidence += 20

        for row in rows:
            if len(row) <= max(roles.values(), default=0):
                # Row doesn't have enough columns — pad
                row = row + [""] * (max(roles.values(), default=0) + 1 - len(row))

            item = {}

            # Description
            if "description" in roles:
                desc = row[roles["description"]].strip()
                # Skip rows that look like headers or totals
                if desc.lower() in ("total", "grand total", "sub total", "subtotal", ""):
                    continue
                if re.match(r"^(total|sub\s*total|grand\s*total|net|tax)", desc, re.IGNORECASE):
                    continue
                item["description"] = desc
            else:
                item["description"] = ""

            # Quantity
            if "quantity" in roles:
                item["quantity"] = _parse_number(row[roles["quantity"]]) or 0
            else:
                item["quantity"] = 0

            # Rate
            if "rate" in roles:
                item["rate"] = _parse_number(row[roles["rate"]]) or 0
            else:
                item["rate"] = 0

            # Amount
            if "amount" in roles:
                item["amount"] = _parse_number(row[roles["amount"]]) or 0
            else:
                # Try to compute from qty * rate
                if item["quantity"] and item["rate"]:
                    item["amount"] = round(item["quantity"] * item["rate"], 2)
                else:
                    item["amount"] = 0

            # HSN
            if "hsn" in roles:
                item["hsn"] = row[roles["hsn"]].strip()
            else:
                item["hsn"] = ""

            # Only include if there's meaningful data
            if item.get("description") or item.get("amount", 0) > 0:
                all_items.append(item)

        best_confidence = max(best_confidence, confidence)

    return all_items, best_confidence


def extract_line_items_from_text(text: str) -> Tuple[List[dict], int]:
    """
    Heuristic fallback: extract line items from raw text when no table is detected.
    Looks for patterns like "Description ... Qty ... Rate ... Amount" in text lines.
    """
    items = []
    lines = text.split("\n")

    # Look for lines that have an amount at the end (common in invoice line items)
    amount_at_end = re.compile(
        r"^(.{5,60}?)\s+"           # description (5-60 chars)
        r"(\d+(?:\.\d+)?)\s+"       # quantity
        r"([\d,]+(?:\.\d{1,2})?)\s+"  # rate
        r"([\d,]+(?:\.\d{1,2})?)$"  # amount
    )

    # Simpler pattern: description followed by amount
    desc_amount = re.compile(
        r"^(.{5,60}?)\s+"           # description
        r"([\d,]+(?:\.\d{1,2})?)$"  # amount at end
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue
        # Skip total/header lines
        if re.match(r"^(total|sub\s*total|grand\s*total|tax|cgst|sgst|igst|hsn|gst)", line, re.IGNORECASE):
            continue

        m = amount_at_end.match(line)
        if m:
            items.append({
                "description": m.group(1).strip(),
                "quantity": float(m.group(2)),
                "rate": float(m.group(3).replace(",", "")),
                "amount": float(m.group(4).replace(",", "")),
                "hsn": "",
            })
            continue

        m = desc_amount.match(line)
        if m:
            desc = m.group(1).strip()
            amt = float(m.group(2).replace(",", ""))
            if amt > 0 and len(desc) > 5:
                items.append({
                    "description": desc,
                    "quantity": 0,
                    "rate": 0,
                    "amount": amt,
                    "hsn": "",
                })

    confidence = 30 if items else 0
    return items, confidence


# ============================================================
# Layout-Aware Section Detection
# ============================================================

def classify_sections(blocks: List[dict], page_height: float = 1000) -> Dict[str, List[dict]]:
    """
    Classify OCR blocks into document sections based on position.

    Sections:
        header:  top 25% — vendor info, logo, GSTIN
        details: 25-40% — invoice number, date, buyer info
        table:   40-75% — line items table
        totals:  bottom 25% — totals, tax summary, bank details

    Falls back to text-based detection if bboxes are missing.
    """
    sections = {"header": [], "details": [], "table": [], "totals": []}

    if not blocks:
        return sections

    # Check if we have bounding boxes
    has_bbox = any(b.get("bbox") and len(b["bbox"]) == 4 and b["bbox"][3] > 0 for b in blocks)

    if has_bbox:
        # Position-based classification
        max_y = max(b["bbox"][3] for b in blocks if b.get("bbox") and len(b["bbox"]) == 4) or page_height

        for block in blocks:
            bbox = block.get("bbox", [])
            if not bbox or len(bbox) < 4:
                sections["details"].append(block)
                continue

            y_pos = bbox[1]  # top of block
            relative = y_pos / max_y if max_y > 0 else 0.5

            if block.get("type") == "table":
                sections["table"].append(block)
            elif relative < 0.25:
                sections["header"].append(block)
            elif relative < 0.4:
                sections["details"].append(block)
            elif relative < 0.75:
                sections["table"].append(block)
            else:
                sections["totals"].append(block)
    else:
        # Text-based fallback: use keywords to classify
        total_lines = len(blocks)
        for i, block in enumerate(blocks):
            text_lower = block.get("text", "").lower()
            relative = i / total_lines if total_lines > 0 else 0.5

            if block.get("type") == "table":
                sections["table"].append(block)
            elif any(kw in text_lower for kw in ["total", "grand total", "amount payable", "bank"]):
                sections["totals"].append(block)
            elif any(kw in text_lower for kw in ["gstin", "gst", "supplier", "seller", "tax invoice"]):
                sections["header"].append(block)
            elif relative < 0.3:
                sections["header"].append(block)
            elif relative < 0.5:
                sections["details"].append(block)
            elif relative < 0.8:
                sections["table"].append(block)
            else:
                sections["totals"].append(block)

    return sections


# ============================================================
# Main Invoice Processor
# ============================================================

class InvoiceProcessor:
    """
    Unified invoice processing pipeline.

    process(file_path, mime_type) → dict with:
        vendor_name, vendor_gstin, invoice_number, invoice_date,
        total_amount, taxable_value, gst_breakdown,
        line_items, confidence_score, flags
    """

    def __init__(self):
        self.ocr = OCRService()
        self.parser = DataParser()
        self.ai_extractor = AIExtractor()

    async def process(self, file_path: str, mime_type: str, retry: bool = True) -> dict:
        """
        Full pipeline: OCR → Layout → Extract → Validate → Result.

        Args:
            file_path: Path to uploaded file
            mime_type: MIME type of file
            retry: Whether to retry OCR on failure (default True)

        Returns:
            Structured invoice dict or failure dict
        """
        # Step 1: OCR with retry
        ocr_result = await self.ocr.extract_text(file_path, mime_type)

        if ocr_result.get("quality") in ("empty", "poor") and retry:
            logger.info("OCR quality poor, retrying...")
            ocr_result_retry = await self.ocr.extract_text(file_path, mime_type)
            # Use retry if it got more text
            if len(ocr_result_retry.get("text", "")) > len(ocr_result.get("text", "")):
                ocr_result = ocr_result_retry

        raw_text = ocr_result.get("text", "")
        if not raw_text.strip():
            return {
                "status": "failed",
                "reason": "OCR_FAILED",
                "ocr_method": ocr_result.get("method", "none"),
                "ocr_quality": ocr_result.get("quality", "empty"),
            }

        blocks = ocr_result.get("blocks", [])
        tables = ocr_result.get("tables", [])
        ocr_confidence = ocr_result.get("confidence", 50)

        # Step 2: Layout analysis
        sections = classify_sections(blocks)

        # Step 3: Hybrid extraction (regex + layout + tables)
        parsed = self.parser.parse_invoice(raw_text)

        # Step 4: Extract line items
        line_items = []
        line_item_confidence = 0

        if tables:
            line_items, line_item_confidence = extract_line_items_from_tables(tables)

        if not line_items:
            # Fallback: try text-based extraction
            line_items, line_item_confidence = extract_line_items_from_text(raw_text)

        # Step 5: Build per-field confidence
        field_confidences = {}
        for field_name in ["gstin", "invoice_number", "invoice_date", "vendor_name",
                           "taxable_amount", "cgst", "sgst", "igst", "total_amount"]:
            field_data = parsed.get(field_name, {})
            field_confidences[field_name] = field_data.get("confidence", 0) / 100.0

        # Step 6: Validation and flags
        flags = []
        val = lambda f: parsed.get(f, {}).get("value")

        # GSTIN validation
        gstin = val("gstin")
        if gstin:
            if not re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]Z[A-Z0-9]$", gstin):
                flags.append("INVALID_GSTIN_FORMAT")
                field_confidences["gstin"] = min(field_confidences.get("gstin", 0), 0.4)
        else:
            flags.append("MISSING_GSTIN")

        if not val("invoice_number"):
            flags.append("MISSING_INVOICE_NUMBER")
        if not val("invoice_date"):
            flags.append("MISSING_INVOICE_DATE")

        # Amount validation
        total = val("total_amount")
        taxable = val("taxable_amount")
        cgst_val = val("cgst") or 0
        sgst_val = val("sgst") or 0
        igst_val = val("igst") or 0
        gst_total = cgst_val + sgst_val + igst_val

        if total and taxable and gst_total > 0:
            expected = taxable + gst_total
            if abs(total - expected) > max(1.0, total * 0.02):
                flags.append("TOTAL_MISMATCH")

        if cgst_val > 0 and sgst_val > 0 and igst_val > 0:
            flags.append("GST_CONFLICT_CGST_SGST_AND_IGST")

        if not line_items:
            flags.append("MISSING_LINE_ITEMS")

        if not total and not taxable:
            flags.append("MISSING_AMOUNTS")

        # Line items vs total validation
        if line_items and taxable:
            items_total = sum(item.get("amount", 0) for item in line_items)
            if items_total > 0 and abs(items_total - taxable) > max(1.0, taxable * 0.05):
                flags.append("LINE_ITEMS_TOTAL_MISMATCH")

        # Step 7: Calculate overall confidence
        weights = {
            "gstin": 2.0, "invoice_number": 2.0, "invoice_date": 1.5,
            "total_amount": 2.0, "taxable_amount": 1.0,
            "cgst": 0.5, "sgst": 0.5, "igst": 0.5,
        }
        total_weight = 0
        weighted_sum = 0
        for field, weight in weights.items():
            conf = field_confidences.get(field, 0)
            if val(field) is not None:
                weighted_sum += conf * weight
                total_weight += weight
            elif field in ("gstin", "invoice_number", "invoice_date", "total_amount"):
                total_weight += weight  # penalize missing critical fields

        confidence_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0

        # Factor in OCR confidence
        confidence_score = round(confidence_score * 0.7 + (ocr_confidence / 100) * 0.3, 2)

        # Reduce confidence based on flags
        penalty = len(flags) * 0.03
        confidence_score = max(0, round(confidence_score - penalty, 2))

        # Step 8: Build initial output
        result = {
            "status": "success",
            "vendor_name": val("vendor_name") or "",
            "vendor_gstin": gstin or "",
            "invoice_number": val("invoice_number") or "",
            "invoice_date": val("invoice_date") or "",
            "total_amount": round(float(total or 0), 2),
            "taxable_value": round(float(taxable or 0), 2),
            "gst_breakdown": {
                "cgst": round(float(cgst_val), 2),
                "sgst": round(float(sgst_val), 2),
                "igst": round(float(igst_val), 2),
            },
            "line_items": line_items,
            "hsn_codes": val("hsn_codes") or [],
            "confidence_score": confidence_score,
            "confidence_details": {k: round(v, 2) for k, v in field_confidences.items()},
            "flags": flags,
            "ocr_metadata": {
                "method": ocr_result.get("method", "none"),
                "quality": ocr_result.get("quality", "empty"),
                "page_count": ocr_result.get("page_count", 0),
                "char_count": ocr_result.get("char_count", 0),
            },
        }

        # Step 9: AI fallback — triggered only when parser is uncertain
        if should_trigger_ai(confidence_score, flags) and self.ai_extractor.available:
            logger.info(
                f"AI extraction triggered: confidence={confidence_score}, flags={len(flags)}"
            )
            try:
                ai_result = await self.ai_extractor.extract(raw_text)
                if ai_result:
                    result = merge_results(result, ai_result, field_confidences)
                    logger.info(
                        f"AI merge complete: "
                        f"ai_fields={result.get('ai_extraction', {}).get('fields_from_ai', [])} "
                        f"new_confidence={result.get('confidence_score')}"
                    )
            except Exception as e:
                logger.warning(f"AI extraction failed (non-fatal): {e}")
                # Parser result stands as-is

        return result
