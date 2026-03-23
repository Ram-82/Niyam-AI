"""
GST Routes — ITC reconciliation and GSTR-2B matching.

POST /api/gst/itc-reconcile   → Run ITC matching against GSTR-2B
GET  /api/gst/itc-summary     → Get latest ITC summary (future)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.security import verify_token
from app.services.itc_service import ITCService
from app.services.itc_matcher import MatchConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gst", tags=["GST"])
security = HTTPBearer()


class ITCReconcileRequest(BaseModel):
    gstr2b_data: dict = Field(..., description="GSTR-2B JSON (official or flat format)")
    period: Optional[str] = Field(None, description="Filing period label, e.g. 'Mar 2026'")
    amount_tolerance: float = Field(1.0, ge=0, le=100, description="Taxable amount tolerance in ₹")
    gst_tolerance: float = Field(1.0, ge=0, le=100, description="GST amount tolerance in ₹")


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


@router.post("/itc-reconcile", response_model=dict)
async def reconcile_itc(
    request: ITCReconcileRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Run ITC reconciliation: match purchase invoices against GSTR-2B.

    Returns:
    - Per-invoice match results with ITC amounts
    - Financial summary (available, claimed, at-risk, recoverable)
    - Vendor reliability scores
    - Prioritized action items
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    # Get business_id
    if is_mock:
        user = db.get_user_by_id(user_id)
        business_id = user["business_id"] if user else None
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = user_resp.data.get("business_id") if user_resp.data else None

    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    # Fetch purchase invoices
    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        inv_resp = (
            db.table("invoices")
            .select("*")
            .eq("business_id", business_id)
            .eq("invoice_type", "purchase")
            .execute()
        )
        invoices = inv_resp.data or []

    if not invoices:
        raise HTTPException(
            status_code=400,
            detail="No purchase invoices found. Upload invoices before running ITC reconciliation.",
        )

    # Run reconciliation
    config = MatchConfig(
        amount_tolerance=request.amount_tolerance,
        gst_tolerance=request.gst_tolerance,
    )
    service = ITCService(config)
    report = service.reconcile(
        invoices=invoices,
        gstr2b_json=request.gstr2b_data,
        period=request.period,
    )

    return {
        "success": True,
        "data": report,
    }
