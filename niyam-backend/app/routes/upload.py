"""
Upload & Extract routes — the entry point of the compliance pipeline.

POST /api/upload   — accept a document, persist to storage, create DB record
POST /api/extract  — download from storage, run OCR + parser
"""

import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException, status
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
from app.services.storage import storage_service
from app.utils.file_validation import verify_magic_bytes, sanitize_filename

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Upload & Extract"])
security = HTTPBearer()

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

    # Verify actual file content matches declared MIME type (prevents spoofing)
    verify_magic_bytes(content, content_type)

    # Validate size
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE // (1024*1024)}MB",
        )

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    doc_id = str(uuid.uuid4())
    ext = ALLOWED_MIME[content_type]
    filename = sanitize_filename(file.filename or f"document{ext}")

    # Mask user_id in log (show only first 8 chars)
    uid_masked = (user_id or "")[:8] + "****"
    logger.info(f"Upload start user={uid_masked} file={filename!r} size={file_size} type={content_type}")

    # Get user's business_id
    db, is_mock = _get_db()
    if is_mock:
        user = db.get_user_by_id(user_id)
        business_id = user["business_id"] if user else None
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = user_resp.data.get("business_id") if user_resp.data else None

    if not business_id:
        raise HTTPException(status_code=403, detail="No business account associated with this user")

    # Persist file via StorageService (Supabase Storage in prod, local disk in dev)
    storage_key = storage_service.build_storage_key(business_id, filename)
    try:
        storage_service.upload(storage_key, content, content_type)
    except Exception as e:
        logger.error(f"Upload storage failed: {e}")
        raise HTTPException(status_code=502, detail="File storage failed")

    now = datetime.now(timezone.utc).isoformat()

    # Create document record — storage_key is the canonical reference
    doc_record = {
        "id": doc_id,
        "business_id": business_id,
        "uploaded_by": user_id,
        "filename": filename,
        "storage_key": storage_key,
        "file_path": storage_key,       # backwards compat for extract route
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
# GET /api/documents/{document_id}/download
# ================================================================
@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Download a previously uploaded document. Tenant-isolated."""
    from fastapi.responses import Response

    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    # Resolve business_id for tenant check
    if is_mock:
        _user = db.get_user_by_id(user_id)
        business_id = _user["business_id"] if _user else None
    else:
        _user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = _user_resp.data.get("business_id") if _user_resp.data else None

    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    # Fetch document with tenant isolation
    if is_mock:
        _doc = db.get_document_by_id(document_id)
        doc = _doc if (_doc and _doc.get("business_id") == business_id) else None
    else:
        doc_resp = (
            db.table("documents")
            .select("*")
            .eq("id", document_id)
            .eq("business_id", business_id)
            .single()
            .execute()
        )
        doc = doc_resp.data

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_key = doc.get("storage_key") or doc.get("file_path", "")
    if not storage_key:
        raise HTTPException(status_code=404, detail="Document file not available")

    try:
        content = storage_service.download(storage_key)
    except Exception as e:
        logger.error(f"Download failed for doc={document_id}: {e}")
        raise HTTPException(status_code=404, detail="Document file not found in storage")

    filename = sanitize_filename(doc.get("filename", "document"))
    mime_type = doc.get("mime_type", "application/octet-stream")

    return Response(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ================================================================
# POST /api/extract
# ================================================================
@router.post("/extract", response_model=dict)
async def extract_document(
    request: Request,
    body: ExtractRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Run OCR + data parsing on an uploaded document."""
    user_id = _get_user_id(credentials)
    doc_id = body.document_id

    db, is_mock = _get_db()

    # Resolve the requesting user's business_id (tenant identity)
    if is_mock:
        _user = db.get_user_by_id(user_id)
        business_id = _user["business_id"] if _user else None
    else:
        _user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = _user_resp.data.get("business_id") if _user_resp.data else None

    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    # Fetch document record — filter by business_id to enforce tenant isolation
    if is_mock:
        _doc = db.get_document_by_id(doc_id)
        doc = _doc if (_doc and _doc.get("business_id") == business_id) else None
    else:
        doc_resp = (
            db.table("documents")
            .select("*")
            .eq("id", doc_id)
            .eq("business_id", business_id)
            .single()
            .execute()
        )
        doc = doc_resp.data

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_key = doc.get("storage_key") or doc.get("file_path", "")
    mime_type = doc.get("mime_type", "application/pdf")
    ext = ALLOWED_MIME.get(mime_type, "")

    # Download file from storage to a temp file for OCR processing
    try:
        file_path = storage_service.download_to_temp(storage_key, suffix=ext)
    except Exception as e:
        logger.error(f"Extract: failed to retrieve document {doc_id}: {e}")
        raise HTTPException(status_code=404, detail="Document file not found in storage")
    _temp_file = file_path  # track so we can clean up

    # Update status to processing
    if is_mock:
        db.update_document_status(doc_id, DocumentStatus.PROCESSING.value)
    else:
        db.table("documents").update({"status": DocumentStatus.PROCESSING.value}).eq("id", doc_id).execute()

    # Step 1: OCR — with timeout to prevent hangs on corrupt/large files
    trace_id = getattr(request.state, "request_id", doc_id[:8]) if hasattr(request, "state") else doc_id[:8]
    logger.info(f"[{trace_id}] OCR start doc={doc_id} mime={mime_type}")
    ocr = OCRService()
    try:
        ocr_result = await asyncio.wait_for(
            ocr.extract_text(file_path, mime_type),
            timeout=settings.OCR_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"[{trace_id}] OCR timeout after {settings.OCR_TIMEOUT}s doc={doc_id}")
        now = datetime.now(timezone.utc).isoformat()
        if is_mock:
            db.update_document_status(doc_id, DocumentStatus.FAILED.value, now)
        else:
            db.table("documents").update({
                "status": DocumentStatus.FAILED.value,
                "processed_at": now,
            }).eq("id", doc_id).execute()
        raise HTTPException(
            status_code=504,
            detail=f"OCR timed out after {settings.OCR_TIMEOUT}s. File may be corrupt or too complex.",
        )
    finally:
        # Clean up the temp file downloaded from storage
        if _temp_file and os.path.exists(_temp_file):
            try:
                os.unlink(_temp_file)
            except OSError:
                pass

    raw_text = ocr_result.get("text", "")
    ocr_quality = ocr_result.get("quality", "empty")
    ocr_method = ocr_result.get("method", "none")
    logger.info(f"[{trace_id}] OCR done method={ocr_method} quality={ocr_quality} chars={len(raw_text)}")

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
    logger.info(f"[{trace_id}] Parse start doc={doc_id}")
    parser = DataParser()
    parsed = parser.parse_invoice(raw_text)
    logger.info(f"[{trace_id}] Parse done invoice_number={parsed.get('invoice_number', {}).get('value', '?')}")

    # Step 3: Normalize — enforce types, reconcile GST, cross-check totals
    now = datetime.now(timezone.utc).isoformat()
    invoice_id = str(uuid.uuid4())
    # business_id already resolved above (from user record, ownership-verified)

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

    logger.info(
        f"[{trace_id}] Extract complete doc={doc_id} invoice={invoice_id} "
        f"confidence={norm.get('confidence_score', 0)} needs_review={norm.get('needs_review', False)}"
    )

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
