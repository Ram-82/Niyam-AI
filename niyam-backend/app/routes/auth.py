import logging
from pydantic import BaseModel, EmailStr

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import UserCreate, UserLogin, UserResponse, BusinessResponse
from app.services.auth_service import AuthService
from app.utils.security import verify_token, blacklist_token
from app.utils.verification import verification_store, password_reset_store
from app.services.email_service import email_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()


def _get_user_name(email: str) -> str:
    """Look up a user's full_name by email (for the welcome email)."""
    try:
        if settings.ENVIRONMENT != "production":
            from app.utils.mock_db import MockDB
            user = MockDB().get_user_by_email(email)
        else:
            from app.database import get_db_client
            db = get_db_client()
            resp = db.table("users").select("full_name").eq("email", email).single().execute()
            user = resp.data
        return (user or {}).get("full_name") or "there"
    except Exception:
        return "there"


@router.post("/signup", response_model=dict, status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserCreate):
    """Register a new user with business. Returns a verification code to confirm email."""
    try:
        auth_service = AuthService()
        result = await auth_service.register_user(user_data)

        # Generate verification code and send via email
        code = verification_store.generate(user_data.email)
        logger.info(f"Verification code generated for {user_data.email[:4]}****")
        email_service.send_verification_email(user_data.email, code)

        # Audit log
        from app.services.audit_service import audit_log
        audit_log(
            result.get("business_id", ""), result.get("user_id", ""),
            "user_signup", resource_type="user", resource_id=result.get("user_id"),
            details={"email": user_data.email, "business_name": user_data.business_name},
        )

        response_data = {
            "success": True,
            "message": "User registered. Please verify your email.",
            "data": result,
            "requires_verification": True,
        }

        # In development: include the code in the response so the user can verify
        # In production: send via email (SendGrid/Resend) and don't expose the code
        if settings.ENVIRONMENT != "production":
            response_data["_dev_verification_code"] = code

        return response_data

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str


@router.post("/verify-email", response_model=dict)
async def verify_email(body: VerifyEmailRequest):
    """Verify email with 6-digit code sent during signup."""
    success, message = verification_store.verify(body.email, body.code)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Mark user as verified in DB
    try:
        auth_service = AuthService()
        auth_service.mark_email_verified(body.email)
    except Exception as e:
        logger.error(f"Failed to mark email verified: {e}")
        raise HTTPException(status_code=500, detail="Verification succeeded but profile update failed")

    logger.info(f"Email verified for {body.email[:4]}****")

    # Send welcome email (non-blocking — failure is logged, not raised)
    user_name = _get_user_name(body.email)
    email_service.send_welcome_email(body.email, user_name)

    return {
        "success": True,
        "message": "Email verified successfully. You can now log in.",
    }


class ResendCodeRequest(BaseModel):
    email: EmailStr


@router.post("/resend-code", response_model=dict)
async def resend_verification_code(body: ResendCodeRequest):
    """Resend verification code to email."""
    # Check the user exists
    auth_service = AuthService()
    user_exists = auth_service.check_user_exists(body.email)
    if not user_exists:
        # Don't reveal whether email exists (security)
        return {"success": True, "message": "If the email is registered, a new code has been sent."}

    code = verification_store.generate(body.email)
    logger.info(f"Verification code resent for {body.email[:4]}****")
    email_service.send_verification_email(body.email, code)

    response = {"success": True, "message": "Verification code sent."}

    # In development: include code in response
    if settings.ENVIRONMENT != "production":
        response["_dev_verification_code"] = code

    return response


@router.post("/login", response_model=dict)
async def login(credentials: UserLogin):
    """Authenticate user and return tokens. Blocks unverified users."""
    try:
        auth_service = AuthService()
        result = await auth_service.authenticate_user(
            email=credentials.email,
            password=credentials.password
        )

        # Check email verification
        if not result.get("email_verified", True):
            # Re-send verification code (and email)
            code = verification_store.generate(credentials.email)
            email_service.send_verification_email(credentials.email, code)
            error_response = {
                "detail": "Email not verified. A new verification code has been sent.",
                "requires_verification": True,
                "email": credentials.email,
            }
            if settings.ENVIRONMENT != "production":
                error_response["_dev_verification_code"] = code
            raise HTTPException(status_code=403, detail=error_response)

        from app.services.audit_service import audit_log
        audit_log(
            result.get("business_id", ""), result.get("user_id", ""),
            "user_login", resource_type="user", resource_id=result.get("user_id"),
        )
        return {
            "success": True,
            "message": "Login successful",
            "data": result
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.get("/me", response_model=dict)
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get current authenticated user details"""
    try:
        token = credentials.credentials
        payload = verify_token(token)
        user_id = payload.get("sub")

        auth_service = AuthService()
        user_data = await auth_service.get_user_profile(user_id)

        return {
            "success": True,
            "data": user_data
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user profile: {str(e)}"
        )


@router.post("/logout", response_model=dict)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Logout user — blacklists the access token so it cannot be reused."""
    token = credentials.credentials
    try:
        payload = verify_token(token)
        expires_at = payload.get("exp")
        blacklist_token(token, expires_at)
    except HTTPException:
        blacklist_token(token)

    return {
        "success": True,
        "message": "Logout successful. Token has been invalidated."
    }


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password", response_model=dict)
async def forgot_password(body: ForgotPasswordRequest):
    """Send a 6-digit password reset code to the user's email."""
    auth_service = AuthService()
    # Always return same message to avoid user enumeration
    if auth_service.check_user_exists(body.email):
        code = password_reset_store.generate(body.email)
        logger.info(f"Password reset code generated for {body.email[:4]}****")
        email_service.send_password_reset_email(body.email, code)
        response: dict = {"success": True, "message": "If the email is registered, a reset code has been sent."}
        if settings.ENVIRONMENT != "production":
            response["_dev_reset_code"] = code
        return response
    return {"success": True, "message": "If the email is registered, a reset code has been sent."}


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


@router.post("/reset-password", response_model=dict)
async def reset_password(body: ResetPasswordRequest):
    """Verify reset code and update the user's password."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    success, message = password_reset_store.verify(body.email, body.code)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    from app.utils.security import hash_password
    auth_service = AuthService()
    try:
        auth_service.update_user_password(body.email, hash_password(body.new_password))
    except Exception as e:
        logger.error(f"Password update failed for {body.email[:4]}****: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password. Please try again.")

    logger.info(f"Password reset successful for {body.email[:4]}****")
    return {"success": True, "message": "Password updated successfully. You can now log in."}


@router.post("/refresh", response_model=dict)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Refresh access token using refresh token"""
    try:
        refresh_token = credentials.credentials
        auth_service = AuthService()
        new_tokens = await auth_service.refresh_token(refresh_token)

        return {
            "success": True,
            "data": new_tokens
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )
