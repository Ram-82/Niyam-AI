"""
Settings Routes — user profile and business settings management.

GET  /api/settings/profile    → get business profile for settings page
PATCH /api/settings/profile   → update business profile fields
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token, validate_gstin, validate_pan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["Settings"])
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


# ================================================================
# GET /api/settings/profile
# ================================================================
@router.get("/profile", response_model=dict)
async def get_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Get business profile for the settings page."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    if is_mock:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        business = db.get_business_by_id(user.get("business_id"))
    else:
        user_resp = db.table("users").select("*").eq("id", user_id).single().execute()
        user = user_resp.data
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        biz_resp = db.table("businesses").select("*").eq("id", user.get("business_id")).single().execute()
        business = biz_resp.data or {}

    # Strip sensitive fields
    user_safe = {k: v for k, v in (user or {}).items() if k != "hashed_password"}

    return {
        "success": True,
        "data": {
            "user": user_safe,
            "business": business or {},
        },
    }


# ================================================================
# PATCH /api/settings/profile
# ================================================================
@router.patch("/profile", response_model=dict)
async def update_profile(
    body: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Update business profile fields.

    Allowed user fields: full_name, phone
    Allowed business fields: legal_name, trade_name, gstin, pan, address, state_code
    """
    USER_FIELDS = {"full_name", "phone"}
    BUSINESS_FIELDS = {"legal_name", "trade_name", "gstin", "pan", "address", "state_code"}

    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    user_updates = {k: v for k, v in body.items() if k in USER_FIELDS}
    biz_updates = {k: v for k, v in body.items() if k in BUSINESS_FIELDS}

    if not user_updates and not biz_updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    # Validate GSTIN/PAN if being changed
    if "gstin" in biz_updates and biz_updates["gstin"]:
        gstin = biz_updates["gstin"].upper().strip()
        if not validate_gstin(gstin):
            raise HTTPException(status_code=400, detail="Invalid GSTIN format")
        biz_updates["gstin"] = gstin

    if "pan" in biz_updates and biz_updates["pan"]:
        pan = biz_updates["pan"].upper().strip()
        if not validate_pan(pan):
            raise HTTPException(status_code=400, detail="Invalid PAN format")
        biz_updates["pan"] = pan

    # Cross-validate GSTIN/PAN
    if "gstin" in biz_updates and "pan" in biz_updates and biz_updates["gstin"] and biz_updates["pan"]:
        if biz_updates["gstin"][2:12] != biz_updates["pan"]:
            raise HTTPException(status_code=400, detail="GSTIN and PAN do not match")

    if is_mock:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        business_id = user.get("business_id")

        if user_updates:
            def _update_user(users):
                for u in users:
                    if u.get("id") == user_id:
                        u.update(user_updates)
                        break
            db._read_modify_write(db.users_file, _update_user)

        if biz_updates and business_id:
            def _update_biz(businesses):
                for b in businesses:
                    if b.get("id") == business_id:
                        b.update(biz_updates)
                        break
            db._read_modify_write(db.businesses_file, _update_biz)
    else:
        if user_updates:
            db.table("users").update(user_updates).eq("id", user_id).execute()

        if biz_updates:
            user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
            business_id = user_resp.data.get("business_id") if user_resp.data else None
            if business_id:
                db.table("businesses").update(biz_updates).eq("id", business_id).execute()

    logger.info(f"profile updated user={user_id[:8]} fields={list(user_updates.keys()) + list(biz_updates.keys())}")

    # Audit log
    from app.services.audit_service import audit_log
    if is_mock:
        user = db.get_user_by_id(user_id)
        business_id = user.get("business_id", "") if user else ""
    audit_log(
        business_id, user_id, "profile_updated",
        resource_type="user", resource_id=user_id,
        details={"updated_fields": list(user_updates.keys()) + list(biz_updates.keys())},
    )

    return {"success": True, "message": "Profile updated successfully"}
