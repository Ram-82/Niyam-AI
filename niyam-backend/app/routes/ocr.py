"""
OCR Route — standalone text extraction endpoint.

POST /api/ocr/extract  → extract raw text + blocks from a document (no parsing/validation)

This is a lower-level endpoint than /api/process-invoice. It only runs OCR
and returns raw text + structural blocks. Useful for debugging or custom parsing.
"""

import asyncio
import os
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.config import settings
from app.services.ocr_service import OCRService
from app.utils.file_validation import verify_magic_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["OCR"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/jpg": ".jpg",
}


@router.post("/extract", response_model=dict)
async def extract_text(
    file: UploadFile = File(...),
):
    """
    Extract raw text from a document using OCR. No authentication required.

    Returns raw text, text blocks with bounding boxes, detected tables,
    OCR method used, quality score, and confidence.
    """
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Allowed: PDF, JPG, PNG",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max: 10MB")

    # Verify actual file content matches declared MIME type (prevents spoofing)
    verify_magic_bytes(content, content_type)

    doc_id = str(uuid.uuid4())
    ext = ALLOWED_MIME[content_type]
    file_path = UPLOAD_DIR / f"{doc_id}{ext}"

    try:
        with open(file_path, "wb") as f:
            f.write(content)

        ocr = OCRService()
        try:
            result = await asyncio.wait_for(
                ocr.extract_text(str(file_path), content_type),
                timeout=settings.OCR_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"OCR timed out after {settings.OCR_TIMEOUT}s",
            }

        return {
            "success": True,
            "data": {
                "text": result.get("text", ""),
                "blocks": result.get("blocks", []),
                "tables": result.get("tables", []),
                "method": result.get("method", "none"),
                "quality": result.get("quality", "empty"),
                "confidence": result.get("confidence", 0),
                "page_count": result.get("page_count", 0),
                "char_count": result.get("char_count", 0),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}", exc_info=True)
        return {"success": False, "error": "OCR processing failed. Please try again."}
    finally:
        try:
            if file_path.exists():
                os.remove(file_path)
        except OSError:
            pass
