import logging
from datetime import datetime, timezone
from typing import Dict
import uuid
from fastapi import HTTPException, status

from app.models.user import UserCreate
from app.config import settings
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    validate_gstin,
    validate_pan,
)

logger = logging.getLogger(__name__)


class AuthService:
    """
    Authentication service using custom JWT only.
    - PROD (ENVIRONMENT=production): uses Supabase as a PostgreSQL database
    - DEV  (ENVIRONMENT=development): falls back to MockDB (JSON files)
    """

    def __init__(self):
        self.use_mock = settings.ENVIRONMENT != "production"

        if self.use_mock:
            from app.utils.mock_db import MockDB
            self.mock_db = MockDB()
            logger.info("Running in DEV mode with MockDB.")
        else:
            from app.database import get_db_client
            self.db = get_db_client()
            if self.db is None:
                raise RuntimeError(
                    "ENVIRONMENT is 'production' but Supabase client could not be initialized. "
                    "Check SUPABASE_URL and SUPABASE_KEY."
                )
            logger.info("Running in PROD mode with Supabase PostgreSQL.")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register_user(self, user_data: UserCreate) -> Dict:
        # Validate GSTIN if provided
        if user_data.gstin:
            gstin = user_data.gstin.upper().strip()
            if not validate_gstin(gstin):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid GSTIN format. Expected: 15-character alphanumeric (e.g. 29ABCDE1234F1Z5)",
                )
            user_data.gstin = gstin

        # Validate PAN if provided
        if user_data.pan:
            pan = user_data.pan.upper().strip()
            if not validate_pan(pan):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid PAN format. Expected: 10-character alphanumeric (e.g. ABCDE1234F)",
                )
            user_data.pan = pan

        # Cross-validate: GSTIN chars 3-12 must match PAN if both provided
        if user_data.gstin and user_data.pan:
            gstin_pan = user_data.gstin[2:12]
            if gstin_pan != user_data.pan:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="GSTIN and PAN do not match. Characters 3-12 of GSTIN must equal PAN.",
                )

        if self.use_mock:
            return self._register_user_mock(user_data)
        return self._register_user_db(user_data)

    def _register_user_db(self, user_data: UserCreate) -> Dict:
        """Register user directly in Supabase PostgreSQL (no Supabase Auth)."""
        try:
            # Check if email already exists
            existing = (
                self.db.table("users")
                .select("id")
                .eq("email", user_data.email)
                .execute()
            )
            if existing.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User already registered",
                )

            user_id = str(uuid.uuid4())
            business_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # Create business
            self.db.table("businesses").insert(
                {
                    "id": business_id,
                    "user_id": user_id,
                    "legal_name": user_data.business_name,
                    "trade_name": user_data.business_name,
                    "gstin": user_data.gstin,
                    "pan": user_data.pan,
                    "created_at": now,
                }
            ).execute()

            # Create user with hashed password
            hashed = hash_password(user_data.password)
            self.db.table("users").insert(
                {
                    "id": user_id,
                    "email": user_data.email,
                    "hashed_password": hashed,
                    "full_name": user_data.full_name,
                    "phone": user_data.phone,
                    "business_id": business_id,
                    "created_at": now,
                }
            ).execute()

            access_token = create_access_token(data={"sub": user_id})
            refresh_token = create_refresh_token(data={"sub": user_id})

            return {
                "user_id": user_id,
                "business_id": business_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user_name": user_data.full_name,
                "business_name": user_data.business_name,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Registration failed: {str(e)}",
            )

    def _register_user_mock(self, user_data: UserCreate) -> Dict:
        if self.mock_db.get_user_by_email(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already registered",
            )

        user_id = str(uuid.uuid4())
        business_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self.mock_db.create_business(
            {
                "id": business_id,
                "user_id": user_id,
                "legal_name": user_data.business_name,
                "trade_name": user_data.business_name,
                "gstin": user_data.gstin,
                "pan": user_data.pan,
                "created_at": now,
            }
        )

        hashed = hash_password(user_data.password)
        self.mock_db.create_user(
            {
                "id": user_id,
                "email": user_data.email,
                "hashed_password": hashed,
                "full_name": user_data.full_name,
                "phone": user_data.phone,
                "business_id": business_id,
                "created_at": now,
                "last_login": None,
            }
        )

        access_token = create_access_token(data={"sub": user_id})
        refresh_token = create_refresh_token(data={"sub": user_id})

        return {
            "user_id": user_id,
            "business_id": business_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_name": user_data.full_name,
            "business_name": user_data.business_name,
        }

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    async def authenticate_user(self, email: str, password: str) -> Dict:
        if self.use_mock:
            return self._authenticate_user_mock(email, password)
        return self._authenticate_user_db(email, password)

    def _authenticate_user_db(self, email: str, password: str) -> Dict:
        """Authenticate against Supabase PostgreSQL directly."""
        try:
            response = (
                self.db.table("users")
                .select("*")
                .eq("email", email)
                .single()
                .execute()
            )
            user = response.data
            if not user or not verify_password(password, user["hashed_password"]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )

            # Update last login
            self.db.table("users").update(
                {"last_login": datetime.now(timezone.utc).isoformat()}
            ).eq("id", user["id"]).execute()

            business = self._get_business_by_id_db(user.get("business_id"))
            business_name = business.get("trade_name", "Business") if business else "Business"

            access_token = create_access_token(data={"sub": user["id"]})
            refresh_token = create_refresh_token(data={"sub": user["id"]})

            return {
                "user_id": user["id"],
                "business_id": user.get("business_id"),
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user_name": user.get("full_name"),
                "business_name": business_name,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

    def _authenticate_user_mock(self, email: str, password: str) -> Dict:
        user = self.mock_db.get_user_by_email(email)
        if not user or not verify_password(password, user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        self.mock_db.update_user_last_login(
            user["id"], datetime.now(timezone.utc).isoformat()
        )

        business = self.mock_db.get_business_by_id(user["business_id"])
        business_name = business["trade_name"] if business else "Business"

        access_token = create_access_token(data={"sub": user["id"]})
        refresh_token = create_refresh_token(data={"sub": user["id"]})

        return {
            "user_id": user["id"],
            "business_id": user["business_id"],
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_name": user["full_name"],
            "business_name": business_name,
        }

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    async def get_user_profile(self, user_id: str) -> Dict:
        if self.use_mock:
            return self._get_user_profile_mock(user_id)
        return self._get_user_profile_db(user_id)

    def _get_user_profile_db(self, user_id: str) -> Dict:
        try:
            user_resp = (
                self.db.table("users")
                .select("*")
                .eq("id", user_id)
                .single()
                .execute()
            )
            user_data = user_resp.data
            if not user_data:
                raise HTTPException(status_code=404, detail="User not found")

            # Strip sensitive fields
            user_data.pop("hashed_password", None)

            business = self._get_business_by_id_db(user_data.get("business_id"))

            return {"user": user_data, "business": business}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch user profile: {e}")
            raise HTTPException(status_code=404, detail="User profile not found")

    def _get_user_profile_mock(self, user_id: str) -> Dict:
        user = self.mock_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        business = self.mock_db.get_business_by_id(user["business_id"])

        user_safe = user.copy()
        user_safe.pop("hashed_password", None)

        return {"user": user_safe, "business": business}

    # ------------------------------------------------------------------
    # Token Refresh
    # ------------------------------------------------------------------
    async def refresh_token(self, refresh_token_str: str) -> Dict:
        try:
            payload = verify_token(refresh_token_str, is_refresh=True)
            user_id = payload.get("sub")

            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )

            new_access_token = create_access_token(data={"sub": user_id})
            new_refresh_token = create_refresh_token(data={"sub": user_id})

            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_business_by_id_db(self, business_id: str) -> dict:
        if not business_id:
            return {}
        try:
            resp = (
                self.db.table("businesses")
                .select("*")
                .eq("id", business_id)
                .single()
                .execute()
            )
            return resp.data or {}
        except Exception:
            return {}
