import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
import uuid
from fastapi import HTTPException, status
try:
    from supabase import Client
except ImportError:
    class Client: pass


from app.models.user import UserCreate, UserResponse, BusinessResponse
from app.database import supabase, supabase_admin
from app.utils.mock_db import MockDB
from app.utils.security import (
    hash_password, 
    verify_password, 
    create_access_token,
    verify_token,
    create_refresh_token
)

logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self):
        self.client: Client = supabase
        self.admin_client: Client = supabase_admin
        self.use_mock = self.client is None or self.admin_client is None
        
        if self.use_mock:
            self.mock_db = MockDB()
            logger.warning("Supabase client not available. Using Mock DB.")
    
    async def register_user(self, user_data: UserCreate) -> Dict:
        """Register a new user with business details"""
        if self.use_mock:
            return self._register_user_mock(user_data)

        try:
            # Check if user already exists
            existing_user = self.client.auth.sign_up({
                "email": user_data.email,
                "password": user_data.password
            })
            
            if existing_user.user:
                # Create business profile
                business_data = {
                    "user_id": existing_user.user.id,
                    "legal_name": user_data.business_name,
                    "trade_name": user_data.business_name,
                    "gstin": user_data.gstin,
                    "pan": user_data.pan,
                    "created_at": datetime.utcnow().isoformat()
                }
                
                # Use admin client to bypass RLS for initial creation
                business_response = self.admin_client.table("businesses").insert(business_data).execute()
                
                # Create user profile
                user_profile = {
                    "id": existing_user.user.id,
                    "email": user_data.email,
                    "full_name": user_data.full_name,
                    "phone": user_data.phone,
                    "business_id": business_response.data[0]["id"],
                    "created_at": datetime.utcnow().isoformat()
                }
                
                self.admin_client.table("users").insert(user_profile).execute()
                
                # Create access token
                access_token = create_access_token(data={"sub": existing_user.user.id})
                refresh_token = create_refresh_token(data={"sub": existing_user.user.id})
                
                return {
                    "user_id": existing_user.user.id,
                    "business_id": business_response.data[0]["id"],
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "user_name": user_data.full_name,
                    "business_name": user_data.business_name
                }
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Registration failed: {str(e)}"
            )

    def _register_user_mock(self, user_data: UserCreate) -> Dict:
        # Check existing
        if self.mock_db.get_user_by_email(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already registered"
            )

        user_id = str(uuid.uuid4())
        business_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Create Business
        business_data = {
            "id": business_id,
            "user_id": user_id,
            "legal_name": user_data.business_name,
            "trade_name": user_data.business_name,
            "gstin": user_data.gstin,
            "pan": user_data.pan,
            "created_at": now
        }
        self.mock_db.create_business(business_data)

        # Create User
        hashed = hash_password(user_data.password)
        user_profile = {
            "id": user_id,
            "email": user_data.email,
            "hashed_password": hashed,
            "full_name": user_data.full_name,
            "phone": user_data.phone,
            "business_id": business_id,
            "created_at": now,
            "last_login": None
        }
        self.mock_db.create_user(user_profile)

        # Tokens
        access_token = create_access_token(data={"sub": user_id})
        refresh_token = create_refresh_token(data={"sub": user_id})

        return {
            "user_id": user_id,
            "business_id": business_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_name": user_data.full_name,
            "business_name": user_data.business_name
        }
    
    async def authenticate_user(self, email: str, password: str) -> Dict:
        """Authenticate user with email and password"""
        if self.use_mock:
            return self._authenticate_user_mock(email, password)

        try:
            # Use Supabase Auth
            auth_response = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if auth_response.user:
                # Update last login
                self.client.table("users").update({
                    "last_login": datetime.utcnow().isoformat()
                }).eq("id", auth_response.user.id).execute()
                
                # Get user profile
                user_profile = self.client.table("users").select("*").eq("id", auth_response.user.id).single().execute()
                
                # Create tokens
                access_token = create_access_token(data={"sub": auth_response.user.id})
                refresh_token = create_refresh_token(data={"sub": auth_response.user.id})
                
                return {
                    "user_id": auth_response.user.id,
                    "business_id": user_profile.data.get("business_id"),
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "user_name": user_profile.data.get("full_name"),
                    "business_name": self._get_business_name(user_profile.data.get("business_id"))
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )
                
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

    def _authenticate_user_mock(self, email: str, password: str) -> Dict:
        user = self.mock_db.get_user_by_email(email)
        if not user or not verify_password(password, user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Update last login
        self.mock_db.update_user_last_login(user["id"], datetime.utcnow().isoformat())
        
        access_token = create_access_token(data={"sub": user["id"]})
        refresh_token = create_refresh_token(data={"sub": user["id"]})
        
        business = self.mock_db.get_business_by_id(user["business_id"])
        business_name = business["trade_name"] if business else "Business"

        return {
            "user_id": user["id"],
            "business_id": user["business_id"],
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_name": user["full_name"],
            "business_name": business_name
        }
    
    async def get_user_profile(self, user_id: str) -> Dict:
        """Get complete user profile with business details"""
        if self.use_mock:
            return self._get_user_profile_mock(user_id)

        try:
            # Get user data
            user_response = self.client.table("users").select("*").eq("id", user_id).single().execute()
            user_data = user_response.data
            
            # Get business data
            business_id = user_data.get("business_id")
            business_response = self.client.table("businesses").select("*").eq("id", business_id).single().execute()
            business_data = business_response.data
            
            return {
                "user": user_data,
                "business": business_data
            }
        except Exception as e:
            logger.error(f"Failed to fetch user profile: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )

    def _get_user_profile_mock(self, user_id: str) -> Dict:
        user = self.mock_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        business = self.mock_db.get_business_by_id(user["business_id"])
        
        # Remove sensitive data
        user_safe = user.copy()
        if "hashed_password" in user_safe:
            del user_safe["hashed_password"]

        return {
            "user": user_safe,
            "business": business
        }
    
    async def refresh_token(self, refresh_token: str) -> Dict:
        """Refresh access token"""
        try:
            # Verify refresh token
            payload = verify_token(refresh_token, is_refresh=True)
            user_id = payload.get("sub")
            
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token"
                )
            
            # Create new tokens
            new_access_token = create_access_token(data={"sub": user_id})
            new_refresh_token = create_refresh_token(data={"sub": user_id})
            
            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token
            }
            
        except Exception as e:
            logger.error(f"Token refresh error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
    
    def _get_business_name(self, business_id: str) -> str:
        """Helper to get business name"""
        if self.use_mock:
           biz = self.mock_db.get_business_by_id(business_id)
           return biz["trade_name"] if biz else "Business"

        try:
            response = self.client.table("businesses").select("trade_name").eq("id", business_id).single().execute()
            return response.data.get("trade_name", "Business")
        except:
            return "Business"
