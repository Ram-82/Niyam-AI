"""
Process Invoice Route — single endpoint for complete invoice processing.

POST /api/process-invoice
    Input: file (PDF/JPG/PNG)
    Output: structured invoice JSON with confidence scoring and flags

This is the production endpoint. Upload + OCR + Parse + Validate in one call.
Auth: OPTIONAL — works with or without Bearer token.
When authenticated, persists document + invoice records to DB.
"""

import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, UploadFile, File, Request, HTTPException, status

from app.config import settings
from app.services.invoice_processor import InvoiceProcessor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Invoice Processing"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/jpg": ".jpg",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _try_get_user_id(request: Request) -> Optional[str]:
    """Extract user ID from Bearer token if present. Returns None if no/invalid token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        from app.utils.security import verify_token
        payload = verify_token(token)
        return payload.get("sub")
    except Exception:
        return None


def _get_db():
    """Get database client (Supabase or MockDB)."""
    if settings.ENVIRONMENT == "production":
        from app.database import get_db_client
        client = get_db_client()
        if not client:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return client, False
    else:
        from app.utils.mock_db import MockDB
        return MockDB(), True


def _get_business_id(db, is_mock: bool, user_id: str) -> Optional[str]:
    """Look up business_id for a user. Returns None on failure."""
    try:
        if is_mock:
            user = db.get_user_by_id(user_id)
            return user["business_id"] if user else None
        else:
            resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
            return resp.data.get("business_id") if resp.data else None
    except Exception as e:
        logger.warning(f"Could not look up business_id for user={user_id[:8]}: {e}")
        return None


def _save_document_record(db, is_mock: bool, doc_id: str, business_id: str,
                           user_id: str, filename: str, file_size: int,
                           content_type: str, now: str) -> None:
    """Persist a document record to the DB."""
    from app.models.document import DocumentType, DocumentStatus
    doc_record = {
        "id": doc_id,
        "business_id": business_id,
        "uploaded_by": user_id,
        "filename": filename,
        "file_path": None,          # file is temp — not kept on disk
        "file_size": file_size,
        "mime_type": content_type,
        "document_type": DocumentType.PURCHASE_INVOICE.value,
        "status": DocumentStatus.EXTRACTED.value,
        "raw_text": None,
        "created_at": now,
        "processed_at": now,
    }
    if is_mock:
        db.create_document(doc_record)
    else:
        db.table("documents").insert(doc_record).execute()


def _save_invoice_record(db, is_mock: bool, invoice_id: str, doc_id: str,
                          business_id: str, result: dict, now: str) -> None:
    """Persist a normalized invoice record derived from the processor result."""
    gst = result.get("gst_breakdown", {})
    flags = result.get("flags", [])
    confidence = result.get("confidence_score", 0.0)
    needs_review = confidence < 0.7 or bool(flags)

    invoice_record = {
        "id": invoice_id,
        "business_id": business_id,
        "document_id": doc_id,
        "source": "ocr",
        "invoice_number": result.get("invoice_number") or None,
        "invoice_date": result.get("invoice_date") or None,
        "vendor_name": result.get("vendor_name") or None,
        "vendor_gstin": result.get("vendor_gstin") or None,
        "taxable_value": round(float(result.get("taxable_value") or 0), 2),
        "cgst": round(float(gst.get("cgst") or 0), 2),
        "sgst": round(float(gst.get("sgst") or 0), 2),
        "igst": round(float(gst.get("igst") or 0), 2),
        "total_amount": round(float(result.get("total_amount") or 0), 2),
        "hsn_codes": result.get("hsn_codes") or [],
        "invoice_type": "purchase",
        "confidence": confidence,
        "needs_review": needs_review,
        "review_notes": ", ".join(flags) if flags else None,
        "created_at": now,
    }
    if is_mock:
        db.create_invoice(invoice_record)
    else:
        db.table("invoices").insert(invoice_record).execute()


@router.post("/process-invoice", response_model=dict)
async def process_invoice(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Process an invoice file end-to-end. **No authentication required.**

    Accepts PDF, JPG, or PNG. Returns structured invoice data with:
    - vendor_name, vendor_gstin
    - invoice_number, invoice_date
    - total_amount, taxable_value
    - gst_breakdown (cgst, sgst, igst)
    - line_items [{description, quantity, rate, amount}]
    - confidence_score (0.0 - 1.0)
    - compliance (GST validation result)
    - flags (validation issues found)

    On OCR failure, returns: {"status": "failed", "reason": "OCR_FAILED"}
    """
    # Auth is optional — extract user_id if token present
    user_id = _try_get_user_id(request)
    uid_log = (user_id or "anonymous")[:8]

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
    original_filename = file.filename or f"document{ext}"
    safe_filename = f"{doc_id}{ext}"
    file_path = UPLOAD_DIR / safe_filename

    try:
        with open(file_path, "wb") as f:
            f.write(content)

        logger.info(
            f"process-invoice start user={uid_log} "
            f"file={original_filename!r} size={file_size} type={content_type}"
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

        # Persist to DB when user is authenticated and processing succeeded
        invoice_id = None
        saved = False
        if user_id and result.get("status") == "success":
            try:
                db, is_mock = _get_db()
                business_id = _get_business_id(db, is_mock, user_id)
                if business_id:
                    invoice_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    _save_document_record(
                        db, is_mock, doc_id, business_id,
                        user_id, original_filename, file_size, content_type, now,
                    )
                    _save_invoice_record(
                        db, is_mock, invoice_id, doc_id,
                        business_id, result, now,
                    )
                    saved = True
                    logger.info(
                        f"process-invoice saved doc={doc_id} invoice={invoice_id} "
                        f"business={business_id[:8]}"
                    )
            except Exception as e:
                # Storage failure is non-fatal — still return extraction result
                logger.error(f"process-invoice storage failed (non-fatal): {e}", exc_info=True)

        # Attach storage IDs to response
        result["document_id"] = doc_id
        if invoice_id:
            result["invoice_id"] = invoice_id
        result["saved"] = saved

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
