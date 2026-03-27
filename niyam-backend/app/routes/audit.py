"""
Audit Log Route — retrieve activity history for the authenticated business.

GET /api/audit-log → paginated list of all logged actions
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Audit"])
security = HTTPBearer()

# Human-readable labels for action types
ACTION_LABELS = {
    "user_signup": "Account created",
    "user_login": "Logged in",
    "invoice_uploaded": "Invoice uploaded & processed",
    "invoice_corrected": "Invoice fields corrected",
    "tds_deadline_filed": "TDS deadline marked as filed",
    "roc_deadline_filed": "ROC deadline marked as filed",
}


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
    except Exception:
        return None


@router.get("/audit-log", response_model=dict)
async def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: Optional[str] = Query(None, description="Filter by action type"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Retrieve audit log for the authenticated user's business.

    Returns a paginated list of all recorded actions: invoice uploads,
    corrections, deadline filings, logins, etc.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    if is_mock:
        # MockDB returns pre-sorted, we paginate here
        all_logs = db.get_audit_logs(business_id, limit=1000, offset=0)
    else:
        query = (
            db.table("audit_logs")
            .select("*")
            .eq("business_id", business_id)
            .order("timestamp", desc=True)
        )
        if action:
            query = query.eq("action", action)
        resp = query.execute()
        all_logs = resp.data or []

    # Filter by action type (for mock)
    if action and is_mock:
        all_logs = [l for l in all_logs if l.get("action") == action]

    total = len(all_logs)
    offset = (page - 1) * page_size
    page_items = all_logs[offset: offset + page_size]

    # Enrich with human-readable labels
    for item in page_items:
        item["action_label"] = ACTION_LABELS.get(item.get("action", ""), item.get("action", ""))

    return {
        "success": True,
        "data": {
            "entries": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 1,
        },
    }
