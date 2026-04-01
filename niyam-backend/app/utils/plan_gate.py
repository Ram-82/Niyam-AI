"""
Plan Gate — FastAPI dependency that checks the user's subscription status.

Usage:
    from app.utils.plan_gate import require_plan

    @router.get("/advanced-analytics")
    async def advanced_analytics(
        user: CurrentUser = Depends(get_current_user_with_business),
        _plan: None = Depends(require_plan("pro")),
    ):
        ...
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
security = HTTPBearer()


def require_plan(required_plan: str = "pro"):
    """
    Return a FastAPI dependency that blocks requests unless the user has an
    active subscription matching *required_plan*.

    If the subscription exists but has expired, the user is automatically
    downgraded to 'free' and receives a 403.
    """

    async def _check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        payload = verify_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        if settings.ENVIRONMENT == "production":
            from app.database import get_db_client
            db = get_db_client()
            is_mock = False
        else:
            from app.utils.mock_db import MockDB
            db = MockDB()
            is_mock = True

        # Look up active subscription
        sub = None
        if is_mock:
            sub = db.get_active_subscription(user_id)
        else:
            try:
                resp = (
                    db.table("subscriptions")
                    .select("*")
                    .eq("user_id", user_id)
                    .eq("status", "active")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                sub = resp.data[0] if resp.data else None
            except Exception:
                sub = None

        # Check plan matches
        if not sub or sub.get("plan") != required_plan:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires the {required_plan} plan.",
            )

        # Check expiry
        expires_at = sub.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_dt < datetime.now(timezone.utc):
                    # Auto-downgrade
                    if is_mock:
                        db.update_subscription_status(sub["id"], "expired")
                        db.update_user_plan(user_id, "free")
                    else:
                        db.table("subscriptions").update({"status": "expired"}).eq("id", sub["id"]).execute()
                        db.table("users").update({"plan": "free"}).eq("id", user_id).execute()

                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Your {required_plan} subscription has expired. Please renew.",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # Can't parse date — allow through

        return None  # All checks passed

    return _check
