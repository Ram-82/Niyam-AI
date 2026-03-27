"""
App-layer tenant isolation.

Provides FastAPI dependencies that extract the authenticated user's identity
from the JWT and resolve their business_id. Route handlers use these to
scope all database queries, ensuring User A can never access User B's data.

This is the PRIMARY enforcement layer. RLS policies are defense-in-depth.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.utils.security import verify_token

security = HTTPBearer(auto_error=False)


class CurrentUser:
    """Holds the authenticated user's identity for the current request."""
    __slots__ = ("user_id", "business_id")

    def __init__(self, user_id: str, business_id: Optional[str] = None):
        self.user_id = user_id
        self.business_id = business_id

    def __repr__(self):
        return f"CurrentUser(user_id={self.user_id}, business_id={self.business_id})"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """
    FastAPI dependency: extracts user_id from the JWT.
    Raises 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: no user identity",
        )

    return CurrentUser(user_id=user_id)


async def get_current_user_with_business(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """
    FastAPI dependency: extracts user_id AND resolves business_id.
    Use this for routes that need tenant-scoped data access.
    Raises 401 if unauthenticated, 403 if no business is linked.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: no user identity",
        )

    # Resolve business_id from user record
    from app.config import settings

    if settings.ENVIRONMENT != "production":
        from app.utils.mock_db import MockDB
        mock_db = MockDB()
        user = mock_db.get_user_by_id(user_id)
    else:
        from app.database import get_db_client
        db = get_db_client()
        try:
            resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
            user = resp.data
        except Exception:
            user = None

    if not user or not user.get("business_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No business linked to this account",
        )

    return CurrentUser(user_id=user_id, business_id=user["business_id"])


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[CurrentUser]:
    """
    FastAPI dependency: returns CurrentUser if authenticated, None otherwise.
    Use for routes where auth is optional (e.g., process-invoice).
    """
    if not credentials:
        return None

    try:
        payload = verify_token(credentials.credentials)
        user_id = payload.get("sub")
        if user_id:
            return CurrentUser(user_id=user_id)
    except HTTPException:
        pass

    return None
