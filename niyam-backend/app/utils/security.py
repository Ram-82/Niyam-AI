from jose import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from fastapi import HTTPException, status

from app.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password for storing"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a stored password against one provided by user"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: Dict[str, Any]) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=30)  # Refresh tokens last 30 days
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def blacklist_token(token: str, expires_at: Optional[float] = None):
    """Add a token to the blacklist so it can no longer be used."""
    from app.utils.token_blacklist import token_blacklist
    token_blacklist.add(token, expires_at)


def verify_token(token: str, is_refresh: bool = False) -> Dict[str, Any]:
    """Verify JWT token and return payload. Rejects blacklisted tokens."""
    from app.utils.token_blacklist import token_blacklist

    # Check blacklist before decoding
    if token_blacklist.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked"
        )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        # Check token type
        token_type = payload.get("type")
        if is_refresh and token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        elif not is_refresh and token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )

        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

def validate_gstin(gstin: str) -> bool:
    """
    Validate GSTIN (Goods and Services Tax Identification Number) format.

    Format: 2-digit state code + 10-char PAN + 1 entity code + Z + 1 check char
    Example: 29ABCDE1234F1Z5
    Pattern: ^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$
    """
    import re
    if not gstin or len(gstin) != 15:
        return False
    gstin = gstin.upper().strip()
    if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$", gstin):
        return False
    # State code must be 01-37 (Indian states/UTs)
    state_code = int(gstin[:2])
    return 1 <= state_code <= 37

def validate_pan(pan: str) -> bool:
    """
    Validate PAN (Permanent Account Number) format.

    Format: 5 letters + 4 digits + 1 letter
    4th char indicates entity type: C=Company, P=Person, H=HUF, F=Firm, A=AOP, T=Trust, etc.
    Example: ABCDE1234F
    """
    import re
    if not pan or len(pan) != 10:
        return False
    pan = pan.upper().strip()
    return bool(re.match(r"^[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z]$", pan))
