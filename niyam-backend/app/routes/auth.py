from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import UserCreate, UserLogin, UserResponse, BusinessResponse
from app.services.auth_service import AuthService
from app.utils.security import verify_token

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()

@router.post("/signup", response_model=dict, status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserCreate):
    """Register a new user with business"""
    try:
        auth_service = AuthService()
        result = await auth_service.register_user(user_data)
        return {
            "success": True,
            "message": "User registered successfully",
            "data": result
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/login", response_model=dict)
async def login(credentials: UserLogin):
    """Authenticate user and return tokens"""
    try:
        auth_service = AuthService()
        result = await auth_service.authenticate_user(
            email=credentials.email,
            password=credentials.password
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
        user_id = verify_token(token)
        
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
    """Logout user (invalidate token on frontend)"""
    return {
        "success": True,
        "message": "Logout successful"
    }

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
