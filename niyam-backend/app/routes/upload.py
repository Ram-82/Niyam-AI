"""
Upload & Extract routes — the entry point of the compliance pipeline.

POST /api/upload   — accept a document, save to disk, create DB record
POST /api/extract  — run OCR + parser on an uploaded document
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token
from app.models.document import (
    DocumentType,
    DocumentStatus,
    DocumentResponse,
    ExtractRequest,
    ExtractionResult,
    ExtractedFieldOut,
)
from app.services.ocr_service import OCRService
from app.services.data_parser import DataParser
from app.services.normalization import normalize_invoice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Upload & Extract"])
security = HTTPBearer()

# Upload directory (relative to backend root)
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Allowed MIME types
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/jpg": ".jpg",
}


def _get_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    payload = verify_token(credentials.credentials)
    return payload.get("sub")


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


# ================================================================
# POST /api/upload
# ================================================================
@router.post("/upload", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("purchase_invoice"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Upload a document (PDF or image) for processing."""
    user_id = _get_user_id(credentials)

    # Validate document type
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {[e.value for e in DocumentType]}",
        )

    # Validate file type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Allowed: {list(ALLOWED_MIME.keys())}",
        )

    # Read file
    content = await file.read()
    file_size = len(content)

    # Validate size
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE // (1024*1024)}MB",
        )

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # Save file
    doc_id = str(uuid.uuid4())
    ext = ALLOWED_MIME[content_type]
    filename = file.filename or f"document{ext}"
    safe_filename = f"{doc_id}{ext}"
    file_path = UPLOAD_DIR / safe_filename

    with open(file_path, "wb") as f:
        f.write(content)

    # Get user's business_id
    db, is_mock = _get_db()
    if is_mock:
        user = db.get_user_by_id(user_id)
        business_id = user["business_id"] if user else "unknown"
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = user_resp.data.get("business_id", "unknown") if user_resp.data else "unknown"

    now = datetime.now(timezone.utc).isoformat()

    # Create document record
    doc_record = {
        "id": doc_id,
        "business_id": business_id,
        "uploaded_by": user_id,
        "filename": filename,
        "file_path": str(file_path),
        "file_size": file_size,
        "mime_type": content_type,
        "document_type": doc_type.value,
        "status": DocumentStatus.UPLOADED.value,
        "raw_text": None,
        "created_at": now,
        "processed_at": None,
    }

    if is_mock:
        db.create_document(doc_record)
    else:
        db.table("documents").insert(doc_record).execute()

    return {
        "success": True,
        "data": {
            "document_id": doc_id,
            "filename": filename,
            "document_type": doc_type.value,
            "status": "uploaded",
            "file_size": file_size,
            "uploaded_at": now,
        },
    }


# ================================================================
# POST /api/extract
# ================================================================
@router.post("/extract", response_model=dict)
async def extract_document(
    request: ExtractRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Run OCR + data parsing on an uploaded document."""
    user_id = _get_user_id(credentials)
    doc_id = request.document_id

    # Fetch document record
    db, is_mock = _get_db()

    if is_mock:
        doc = db.get_document_by_id(doc_id)
    else:
        doc_resp = db.table("documents").select("*").eq("id", doc_id).single().execute()
        doc = doc_resp.data

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = doc.get("file_path", "")
    mime_type = doc.get("mime_type", "application/pdf")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    # Update status to processing
    if is_mock:
        db.update_document_status(doc_id, DocumentStatus.PROCESSING.value)
    else:
        db.table("documents").update({"status": DocumentStatus.PROCESSING.value}).eq("id", doc_id).execute()

    # Step 1: OCR
    ocr = OCRService()
    ocr_result = await ocr.extract_text(file_path, mime_type)

    raw_text = ocr_result.get("text", "")
    ocr_quality = ocr_result.get("quality", "empty")
    ocr_method = ocr_result.get("method", "none")

    # Save raw text to document record
    if is_mock:
        db.update_document_raw_text(doc_id, raw_text)
    else:
        db.table("documents").update({"raw_text": raw_text}).eq("id", doc_id).execute()

    # Step 2: Parse
    if not raw_text.strip():
        # OCR failed — mark as failed
        now = datetime.now(timezone.utc).isoformat()
        if is_mock:
            db.update_document_status(doc_id, DocumentStatus.FAILED.value, now)
        else:
            db.table("documents").update({
                "status": DocumentStatus.FAILED.value,
                "processed_at": now,
            }).eq("id", doc_id).execute()

        return {
            "success": False,
            "error": "OCR extracted no text from document",
            "data": {
                "document_id": doc_id,
                "status": "failed",
                "ocr_quality": ocr_quality,
                "ocr_method": ocr_method,
            },
        }

    # Step 2: Parse raw text into per-field extractions
    parser = DataParser()
    parsed = parser.parse_invoice(raw_text)

    # Step 3: Normalize — enforce types, reconcile GST, cross-check totals
    now = datetime.now(timezone.utc).isoformat()
    invoice_id = str(uuid.uuid4())
    business_id = doc.get("business_id", "unknown")

    normalized = normalize_invoice(parsed, invoice_id)
    norm = normalized.to_dict()

    # Step 4: Save normalized invoice to DB
    invoice_record = {
        "id": invoice_id,
        "business_id": business_id,
        "document_id": doc_id,
        "source": "ocr",
        "invoice_number": norm["invoice_number"],
        "invoice_date": norm["invoice_date"],
        "vendor_name": norm["vendor_name"],
        "vendor_gstin": norm["gstin"],
        "taxable_value": norm["taxable_amount"] or 0,
        "cgst": norm["cgst"] or 0,
        "sgst": norm["sgst"] or 0,
        "igst": norm["igst"] or 0,
        "total_amount": norm["total_amount"] or 0,
        "hsn_codes": norm["hsn_codes"] or [],
        "invoice_type": doc.get("document_type", "purchase"),
        "confidence": norm["confidence_score"],
        "needs_review": norm["needs_review"],
        "review_notes": ",".join(norm["review_reasons"]) if norm["review_reasons"] else None,
        "created_at": now,
    }

    if is_mock:
        db.create_invoice(invoice_record)
    else:
        db.table("invoices").insert(invoice_record).execute()

    # Update document status
    if is_mock:
        db.update_document_status(doc_id, DocumentStatus.EXTRACTED.value, now)
    else:
        db.table("documents").update({
            "status": DocumentStatus.EXTRACTED.value,
            "processed_at": now,
        }).eq("id", doc_id).execute()

    return {
        "success": True,
        "data": {
            "document_id": doc_id,
            "invoice_id": invoice_id,
            "status": "extracted",
            "ocr_quality": ocr_quality,
            "ocr_method": ocr_method,
            "raw_extraction": parsed,
            "normalized": norm,
        },
    }
