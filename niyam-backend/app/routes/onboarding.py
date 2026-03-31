"""
Onboarding Routes — guide new users through initial setup.

GET  /api/onboarding/status   → check onboarding completion state
POST /api/onboarding/seed     → seed deadlines for the business (called after profile setup)
"""

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token
from app.services.rules.deadline_rules import generate_deadlines_for_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])
security = HTTPBearer()


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


@router.get("/status", response_model=dict)
async def get_onboarding_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Check what onboarding steps the user has completed.

    Returns:
        has_gstin: bool — business has a GSTIN configured
        has_invoices: bool — at least one invoice has been processed
        has_deadlines: bool — deadlines have been seeded
        completed: bool — all steps done
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    # Get user + business
    if is_mock:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        business_id = user.get("business_id")
        business = db.get_business_by_id(business_id) if business_id else {}
        invoices = db.get_invoices_by_business(business_id) if business_id else []
        deadlines = db.get_deadlines_by_business(business_id) if business_id else []
    else:
        user_resp = db.table("users").select("*").eq("id", user_id).single().execute()
        user = user_resp.data
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        business_id = user.get("business_id")

        biz_resp = db.table("businesses").select("*").eq("id", business_id).single().execute()
        business = biz_resp.data or {}

        inv_resp = db.table("invoices").select("id").eq("business_id", business_id).limit(1).execute()
        invoices = inv_resp.data or []

        dl_resp = db.table("deadlines").select("id").eq("business_id", business_id).limit(1).execute()
        deadlines = dl_resp.data or []

    has_gstin = bool(business.get("gstin"))
    has_invoices = len(invoices) > 0
    has_deadlines = len(deadlines) > 0
    completed = has_gstin and has_invoices and has_deadlines

    return {
        "success": True,
        "data": {
            "has_gstin": has_gstin,
            "has_pan": bool(business.get("pan")),
            "has_invoices": has_invoices,
            "has_deadlines": has_deadlines,
            "completed": completed,
            "business_name": business.get("legal_name") or business.get("trade_name") or "",
            "gstin": business.get("gstin") or "",
        },
    }


@router.post("/seed", response_model=dict)
async def seed_deadlines(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Seed statutory deadlines (GST, TDS, ROC) for the user's business.
    Idempotent — skips if deadlines already exist for current year.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    if is_mock:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        business_id = user.get("business_id")
        existing = db.get_deadlines_by_business(business_id) if business_id else []
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        business_id = user_resp.data.get("business_id") if user_resp.data else None
        if not business_id:
            raise HTTPException(status_code=404, detail="Business not found")
        dl_resp = db.table("deadlines").select("id").eq("business_id", business_id).limit(1).execute()
        existing = dl_resp.data or []

    current_year = date.today().year
    year_prefix = str(current_year)
    has_current = any(dl.get("due_date", "").startswith(year_prefix) for dl in existing)

    if has_current:
        return {"success": True, "message": "Deadlines already seeded", "seeded": 0}

    all_deadlines = generate_deadlines_for_year(current_year)
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for dl in all_deadlines:
        dl["id"] = str(uuid.uuid4())
        dl["business_id"] = business_id
        dl["status"] = "upcoming"
        dl["filed_at"] = None
        dl["created_at"] = now

        if is_mock:
            db.upsert_deadline(dl)
        else:
            db.table("deadlines").insert(dl).execute()
        count += 1

    logger.info(f"Onboarding: seeded {count} deadlines for business={business_id[:8]}")

    from app.services.audit_service import audit_log
    audit_log(business_id, user_id, "deadlines_seeded",
              details={"count": count, "year": current_year})

    return {"success": True, "message": f"Seeded {count} deadlines", "seeded": count}
