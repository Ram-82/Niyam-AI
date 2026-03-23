"""
Compliance check route — run Rules Engine against business data.

POST /api/compliance-check
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.config import settings
from app.utils.security import verify_token
from app.services.rules import RulesEngine
from app.services.rules.deadline_rules import generate_deadlines_for_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Compliance"])
security = HTTPBearer()


class ComplianceCheckRequest(BaseModel):
    check_type: str = "all"  # "all", "gst", "tds", "roc", "invoice"


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


@router.post("/compliance-check", response_model=dict)
async def run_compliance_check(
    request: ComplianceCheckRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Run Rules Engine against the user's business data.
    Returns compliance flags, score, risk level, and estimated penalties.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    # Get user's business_id
    if is_mock:
        user = db.get_user_by_id(user_id)
        business_id = user["business_id"] if user else None
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = user_resp.data.get("business_id") if user_resp.data else None

    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    # Fetch deadlines
    deadlines = []
    if request.check_type in ("all", "gst", "tds", "roc"):
        if is_mock:
            # Generate statutory deadlines for current year
            deadlines = generate_deadlines_for_year(date.today().year)
        else:
            dl_resp = db.table("compliance_deadlines").select("*").eq("business_id", business_id).execute()
            deadlines = dl_resp.data or []
            # If no deadlines in DB, generate defaults
            if not deadlines:
                deadlines = generate_deadlines_for_year(date.today().year)

        # Filter by check_type if not "all"
        if request.check_type != "all":
            deadlines = [d for d in deadlines if d.get("type") == request.check_type]

    # Fetch invoices
    invoices = []
    if request.check_type in ("all", "invoice"):
        if is_mock:
            invoices = db.get_invoices_by_business(business_id)
        else:
            inv_resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
            invoices = inv_resp.data or []

    # Run Rules Engine
    engine = RulesEngine()
    report = engine.run_all(
        deadlines=deadlines,
        invoices=invoices,
    )

    return {
        "success": True,
        "data": report,
    }
