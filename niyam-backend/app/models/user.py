from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = None

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    business_name: str = Field(..., min_length=2, max_length=200)
    gstin: Optional[str] = None
    pan: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(UserBase):
    id: str
    business_id: str
    created_at: datetime
    last_login: Optional[datetime]
    
    class Config:
        from_attributes = True

class BusinessBase(BaseModel):
    legal_name: str
    trade_name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    business_type: str = "Proprietorship"
    address: Optional[str] = None
    state_code: Optional[str] = None
    is_msme_registered: bool = False
    msme_number: Optional[str] = None

class BusinessResponse(BusinessBase):
    id: str
    user_id: str
    created_at: datetime
    
    class Config:
        from_attributes = True
