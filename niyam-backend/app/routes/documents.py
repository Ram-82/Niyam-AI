"""
Documents Route — list, download, and delete uploaded documents.

GET    /api/documents              — list all documents (paginated)
GET    /api/documents/{id}/download — download original file
DELETE /api/documents/{id}         — delete document record + file
"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Documents"])
security = HTTPBearer()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _get_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    payload = verify_token(credentials.credentials)
    return payload.get("sub")


def _get_db():
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
    try:
        if is_mock:
            user = db.get_user_by_id(user_id)
            return user["business_id"] if user else None
        else:
            resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
            return resp.data.get("business_id") if resp.data else None
    except Exception as e:
        logger.warning(f"Failed to look up business_id for user={user_id[:8]}: {e}")
        return None


@router.get("/documents", response_model=dict)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """List all documents uploaded by the authenticated user's business."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    if is_mock:
        all_docs = db.get_documents_by_business(business_id)
    else:
        resp = (
            db.table("documents")
            .select("*")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .execute()
        )
        all_docs = resp.data or []

    # Annotate each document with whether its file is currently on disk
    for doc in all_docs:
        fp = doc.get("file_path")
        doc["file_available"] = bool(fp and (UPLOAD_DIR / fp).exists())

    total = len(all_docs)
    offset = (page - 1) * page_size
    page_items = all_docs[offset: offset + page_size]

    return {
        "success": True,
        "data": {
            "documents": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 1,
        },
    }


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Download the original uploaded file for a document."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    # Fetch document with tenant isolation
    if is_mock:
        doc = db.get_document_by_id(doc_id)
        if not doc or doc.get("business_id") != business_id:
            raise HTTPException(status_code=404, detail="Document not found")
    else:
        resp = (
            db.table("documents")
            .select("*")
            .eq("id", doc_id)
            .eq("business_id", business_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Document not found")
        doc = resp.data

    file_path_rel = doc.get("file_path")
    if not file_path_rel:
        raise HTTPException(
            status_code=410,
            detail="Original file not available. Files are kept for 30 days after upload.",
        )

    full_path = UPLOAD_DIR / file_path_rel
    if not full_path.exists():
        raise HTTPException(
            status_code=410,
            detail="Original file has been removed. Files are retained for 30 days after upload.",
        )

    mime_type = doc.get("mime_type", "application/octet-stream")
    original_filename = doc.get("filename", file_path_rel)

    return FileResponse(
        path=str(full_path),
        media_type=mime_type,
        filename=original_filename,
    )


@router.delete("/documents/{doc_id}", response_model=dict)
async def delete_document(
    doc_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Delete a document record and its associated file."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    if is_mock:
        doc = db.get_document_by_id(doc_id)
        if not doc or doc.get("business_id") != business_id:
            raise HTTPException(status_code=404, detail="Document not found")
        file_path_rel = doc.get("file_path")
        db.delete_document(doc_id)
    else:
        resp = (
            db.table("documents")
            .select("id, file_path")
            .eq("id", doc_id)
            .eq("business_id", business_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Document not found")
        file_path_rel = resp.data.get("file_path")
        db.table("documents").delete().eq("id", doc_id).execute()

    # Remove file from disk if present
    if file_path_rel:
        full_path = UPLOAD_DIR / file_path_rel
        try:
            if full_path.exists():
                os.remove(full_path)
        except OSError as e:
            logger.warning(f"Could not delete file {full_path}: {e}")

    logger.info(f"Document deleted: doc={doc_id} by user={user_id[:8]}")

    from app.services.audit_service import audit_log
    audit_log(
        business_id, user_id, "document_deleted",
        resource_type="document", resource_id=doc_id,
        details={},
    )

    return {"success": True, "message": "Document deleted"}
