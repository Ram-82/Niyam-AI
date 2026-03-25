"""
AI Extractor — LLM-based fallback for invoice data extraction.

Triggered ONLY when rule-based parser has low confidence (< 0.75) or too many flags (> 2).
Uses Claude API to extract structured data from OCR text.

Design principles:
1. NEVER replaces the parser — only supplements it
2. Strict prompt prevents hallucination ("return null if unsure")
3. Same validation rules applied to AI output
4. Graceful degradation: if AI fails, parser result stands
5. Cost-aware: only called when needed, truncates long text
"""

import json
import logging
import time
from typing import Optional, Dict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

# Thresholds for triggering AI extraction
AI_TRIGGER_CONFIDENCE = 0.75   # Below this → trigger AI
AI_TRIGGER_FLAG_COUNT = 2      # More than this → trigger AI
AI_MAX_INPUT_CHARS = 4000      # Truncate OCR text to control cost
AI_TIMEOUT_SECONDS = 15        # Max wait for AI response

# The extraction prompt — strict, no-hallucination design
_SYSTEM_PROMPT = """You are a precise invoice data extractor. You extract structured data from Indian invoices (GST invoices, tax invoices, bills).

RULES:
- Extract ONLY what is explicitly present in the text
- If a field is not found, return null — do NOT guess
- Do NOT invent or hallucinate values
- GSTIN must be exactly 15 characters (2 digits + PAN + entity + Z + check)
- Dates must be real dates found in the text
- Amounts must be numbers found in the text
- For line items, only include rows you can clearly identify

Return valid JSON only. No markdown, no explanation."""

_USER_PROMPT_TEMPLATE = """Extract invoice data from this document text:

---
{ocr_text}
---

Return this exact JSON structure (null for missing fields):
{{
  "vendor_name": "string or null",
  "vendor_gstin": "15-char GSTIN or null",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "total_amount": number or null,
  "taxable_value": number or null,
  "cgst": number or null,
  "sgst": number or null,
  "igst": number or null,
  "line_items": [
    {{"description": "string", "quantity": number, "rate": number, "amount": number}}
  ] or []
}}"""


# ============================================================
# AI Extractor
# ============================================================

class AIExtractor:
    """
    LLM-based invoice extraction fallback.

    Usage:
        extractor = AIExtractor()
        if extractor.available:
            result = await extractor.extract(ocr_text)
    """

    def __init__(self):
        self._api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
        self._model = "claude-haiku-4-5-20251001"  # Fast + cheap for extraction
        self._client = None

    @property
    def available(self) -> bool:
        """Check if AI extraction is configured."""
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(AI_TIMEOUT_SECONDS, connect=5.0),
            )
        return self._client

    async def extract(self, ocr_text: str) -> Optional[dict]:
        """
        Call Claude API to extract structured invoice data.

        Args:
            ocr_text: Raw OCR text (will be truncated if too long)

        Returns:
            Parsed dict with invoice fields, or None if failed
        """
        if not self.available:
            logger.debug("AI extractor not available (no API key)")
            return None

        # Truncate to control cost
        truncated = ocr_text[:AI_MAX_INPUT_CHARS]
        if len(ocr_text) > AI_MAX_INPUT_CHARS:
            truncated += "\n[... text truncated ...]"

        user_prompt = _USER_PROMPT_TEMPLATE.format(ocr_text=truncated)

        t0 = time.time()
        try:
            client = self._get_client()
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 1024,
                    "system": _SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": user_prompt}
                    ],
                },
            )

            elapsed = round(time.time() - t0, 2)

            if response.status_code != 200:
                logger.warning(
                    f"AI extraction failed: HTTP {response.status_code} "
                    f"({elapsed}s) body={response.text[:200]}"
                )
                return None

            data = response.json()
            content = data.get("content", [])
            if not content:
                logger.warning("AI extraction returned empty content")
                return None

            # Extract text from response
            text_block = next((b["text"] for b in content if b.get("type") == "text"), None)
            if not text_block:
                return None

            # Parse JSON from response (handle potential markdown wrapping)
            json_text = text_block.strip()
            if json_text.startswith("```"):
                # Strip markdown code fences
                lines = json_text.split("\n")
                json_text = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            result = json.loads(json_text)

            # Basic sanity check: must be a dict
            if not isinstance(result, dict):
                logger.warning(f"AI extraction returned non-dict: {type(result)}")
                return None

            logger.info(
                f"AI extraction success ({elapsed}s) "
                f"fields_found={sum(1 for v in result.values() if v is not None)}"
            )

            return _sanitize_ai_output(result)

        except json.JSONDecodeError as e:
            logger.warning(f"AI extraction returned invalid JSON: {e}")
            return None
        except httpx.TimeoutException:
            elapsed = round(time.time() - t0, 2)
            logger.warning(f"AI extraction timed out after {elapsed}s")
            return None
        except Exception as e:
            logger.error(f"AI extraction error: {e}", exc_info=True)
            return None


def _sanitize_ai_output(raw: dict) -> dict:
    """
    Sanitize AI output to prevent hallucination/injection.
    Enforces types and reasonable value ranges.
    """
    result = {}

    # String fields — must be string or null, max 200 chars
    for field in ("vendor_name", "vendor_gstin", "invoice_number", "invoice_date"):
        val = raw.get(field)
        if isinstance(val, str) and len(val) <= 200:
            result[field] = val.strip()
        else:
            result[field] = None

    # GSTIN must be exactly 15 chars
    gstin = result.get("vendor_gstin")
    if gstin and len(gstin) != 15:
        result["vendor_gstin"] = None

    # Date must look like YYYY-MM-DD
    date_val = result.get("invoice_date")
    if date_val:
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
            result["invoice_date"] = None

    # Numeric fields — must be number, >= 0, <= 10 crore (reasonable invoice max)
    MAX_AMOUNT = 100_000_000  # 10 crore
    for field in ("total_amount", "taxable_value", "cgst", "sgst", "igst"):
        val = raw.get(field)
        if isinstance(val, (int, float)) and 0 <= val <= MAX_AMOUNT:
            result[field] = round(float(val), 2)
        else:
            result[field] = None

    # Line items — must be list of dicts
    raw_items = raw.get("line_items", [])
    items = []
    if isinstance(raw_items, list):
        for item in raw_items[:50]:  # Cap at 50 items
            if not isinstance(item, dict):
                continue
            sanitized_item = {
                "description": str(item.get("description", ""))[:200],
                "quantity": 0,
                "rate": 0,
                "amount": 0,
                "hsn": str(item.get("hsn", ""))[:10],
            }
            for num_field in ("quantity", "rate", "amount"):
                val = item.get(num_field)
                if isinstance(val, (int, float)) and 0 <= val <= MAX_AMOUNT:
                    sanitized_item[num_field] = round(float(val), 2)

            if sanitized_item["description"] or sanitized_item["amount"] > 0:
                items.append(sanitized_item)

    result["line_items"] = items

    return result


# ============================================================
# Merge Logic — combine parser + AI results
# ============================================================

def should_trigger_ai(confidence_score: float, flags: list) -> bool:
    """Determine if AI extraction should be triggered."""
    return confidence_score < AI_TRIGGER_CONFIDENCE or len(flags) > AI_TRIGGER_FLAG_COUNT


def merge_results(parser_result: dict, ai_result: dict, parser_confidences: dict) -> dict:
    """
    Merge parser and AI extraction results.

    Strategy: parser-first, AI fills gaps.
    - If parser has a field with confidence > 0.8 → keep parser value
    - If parser has a field with confidence 0.5-0.8 → keep parser, boost confidence
    - If parser missed a field and AI found it → use AI value
    - Line items: use whichever source found more

    Args:
        parser_result: The full result dict from InvoiceProcessor
        ai_result: Sanitized output from AIExtractor
        parser_confidences: Per-field confidence dict from parser (0.0-1.0)

    Returns:
        Updated parser_result with AI-augmented values
    """
    if not ai_result:
        return parser_result

    merged = dict(parser_result)
    ai_used_fields = []

    # Merge scalar fields
    field_map = {
        "vendor_name": "vendor_name",
        "vendor_gstin": "vendor_gstin",
        "invoice_number": "invoice_number",
        "invoice_date": "invoice_date",
        "total_amount": "total_amount",
        "taxable_value": "taxable_value",
    }

    for parser_field, ai_field in field_map.items():
        parser_val = merged.get(parser_field)
        ai_val = ai_result.get(ai_field)
        parser_conf = parser_confidences.get(
            parser_field.replace("vendor_gstin", "gstin").replace("taxable_value", "taxable_amount"),
            0,
        )

        # Parser has high confidence → keep parser
        if parser_val and parser_conf > 0.8:
            continue

        # Parser has value but medium confidence → keep parser, AI confirms
        if parser_val and parser_conf > 0.5:
            if ai_val and str(ai_val).strip() == str(parser_val).strip():
                # AI confirms parser → boost confidence
                conf_key = parser_field.replace("vendor_gstin", "gstin").replace("taxable_value", "taxable_amount")
                if conf_key in merged.get("confidence_details", {}):
                    merged["confidence_details"][conf_key] = min(
                        merged["confidence_details"][conf_key] + 0.1, 0.95
                    )
            continue

        # Parser missed or has low confidence → use AI
        if ai_val is not None and not parser_val:
            merged[parser_field] = ai_val
            ai_used_fields.append(parser_field)
        elif ai_val is not None and parser_conf < 0.5:
            merged[parser_field] = ai_val
            ai_used_fields.append(parser_field)

    # Merge GST breakdown
    for gst_field in ("cgst", "sgst", "igst"):
        parser_val = merged.get("gst_breakdown", {}).get(gst_field, 0)
        ai_val = ai_result.get(gst_field)
        if (not parser_val or parser_val == 0) and ai_val and ai_val > 0:
            merged.setdefault("gst_breakdown", {})[gst_field] = ai_val
            ai_used_fields.append(f"gst_{gst_field}")

    # Merge line items: use whichever found more
    parser_items = merged.get("line_items", [])
    ai_items = ai_result.get("line_items", [])
    if len(ai_items) > len(parser_items) and len(ai_items) > 0:
        merged["line_items"] = ai_items
        ai_used_fields.append("line_items")
        # Remove MISSING_LINE_ITEMS flag if AI found items
        if "MISSING_LINE_ITEMS" in merged.get("flags", []):
            merged["flags"].remove("MISSING_LINE_ITEMS")

    # Update confidence if AI helped
    if ai_used_fields:
        merged["confidence_score"] = min(
            round(merged.get("confidence_score", 0) + 0.1, 2),
            0.95,
        )
        merged["ai_extraction"] = {
            "used": True,
            "fields_from_ai": ai_used_fields,
        }

        # Remove flags that AI resolved
        remaining_flags = []
        for flag in merged.get("flags", []):
            if flag == "MISSING_GSTIN" and "vendor_gstin" in ai_used_fields:
                continue
            if flag == "MISSING_INVOICE_NUMBER" and "invoice_number" in ai_used_fields:
                continue
            if flag == "MISSING_INVOICE_DATE" and "invoice_date" in ai_used_fields:
                continue
            if flag == "MISSING_AMOUNTS" and ("total_amount" in ai_used_fields or "taxable_value" in ai_used_fields):
                continue
            remaining_flags.append(flag)
        merged["flags"] = remaining_flags
    else:
        merged["ai_extraction"] = {"used": True, "fields_from_ai": []}

    return merged
