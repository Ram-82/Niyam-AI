"""
Process Invoice Route — single endpoint for complete invoice processing.

POST /api/process-invoice
    Input: file (PDF/JPG/PNG)
    Output: structured invoice JSON with confidence scoring and flags

This is the production endpoint. Upload + OCR + Parse + Validate in one call.
"""

import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token
from app.services.invoice_processor import InvoiceProcessor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Invoice Processing"])
security = HTTPBearer()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/jpg": ".jpg",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _get_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    payload = verify_token(credentials.credentials)
    return payload.get("sub")


@router.post("/process-invoice", response_model=dict)
async def process_invoice(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Process an invoice file end-to-end.

    Accepts PDF, JPG, or PNG. Returns structured invoice data with:
    - vendor_name, vendor_gstin
    - invoice_number, invoice_date
    - total_amount, taxable_value
    - gst_breakdown (cgst, sgst, igst)
    - line_items [{description, quantity, rate, amount}]
    - confidence_score (0.0 - 1.0)
    - flags (validation issues found)

    On OCR failure, returns: {"status": "failed", "reason": "OCR_FAILED"}
    """
    user_id = _get_user_id(credentials)

    # Validate file type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Allowed: PDF, JPG, PNG",
        )

    # Read and validate size
    content = await file.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({file_size // (1024*1024)}MB). Max: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Save temporarily
    doc_id = str(uuid.uuid4())
    ext = ALLOWED_MIME[content_type]
    safe_filename = f"{doc_id}{ext}"
    file_path = UPLOAD_DIR / safe_filename

    try:
        with open(file_path, "wb") as f:
            f.write(content)

        uid_masked = (user_id or "")[:8] + "****"
        logger.info(
            f"process-invoice start user={uid_masked} "
            f"file={file.filename!r} size={file_size} type={content_type}"
        )

        # Run the processing pipeline with timeout
        processor = InvoiceProcessor()
        try:
            result = await asyncio.wait_for(
                processor.process(str(file_path), content_type),
                timeout=settings.OCR_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(f"process-invoice timeout after {settings.OCR_TIMEOUT}s doc={doc_id}")
            return {
                "status": "failed",
                "reason": "PROCESSING_TIMEOUT",
                "detail": f"Processing timed out after {settings.OCR_TIMEOUT}s",
            }

        logger.info(
            f"process-invoice complete doc={doc_id} "
            f"status={result.get('status')} confidence={result.get('confidence_score', 0)} "
            f"flags={result.get('flags', [])}"
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"process-invoice failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "reason": "PROCESSING_ERROR",
            "detail": str(e),
        }
    finally:
        # Clean up temp file
        try:
            if file_path.exists():
                os.remove(file_path)
        except OSError:
            pass
