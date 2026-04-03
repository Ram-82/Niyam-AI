import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime

_STRICT_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,10}$"
)


def _validate_email_strict(v: str) -> str:
    if not _STRICT_EMAIL_RE.match(v):
        raise ValueError("Invalid email address — check the domain (e.g. john@example.com)")
    return v


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = None

    @field_validator("email")
    @classmethod
    def email_strict(cls, v: str) -> str:
        return _validate_email_strict(v)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    business_name: str = Field(..., min_length=2, max_length=200)
    gstin: Optional[str] = None
    pan: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def email_strict(cls, v: str) -> str:
        return _validate_email_strict(v)

class UserResponse(UserBase):
    id: str
    business_id: str
    email_verified: bool = False
    plan: str = "free"
    created_at: datetime
    last_login: Optional[datetime] = None

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
