"""Tests for Security utilities — password hashing, JWT tokens, token blacklist."""

import pytest
import time
from datetime import timedelta

from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    blacklist_token,
    validate_gstin,
    validate_pan,
)
from app.utils.token_blacklist import TokenBlacklist
from fastapi import HTTPException


# ============================================================
# Password Hashing
# ============================================================

class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "SecureP@ssw0rd!"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_unique(self):
        """Same password should produce different hashes (salt)."""
        h1 = hash_password("test")
        h2 = hash_password("test")
        assert h1 != h2  # Different salts


# ============================================================
# JWT Tokens
# ============================================================

class TestJWTTokens:
    def test_create_and_verify_access_token(self):
        token = create_access_token(data={"sub": "user-123"})
        payload = verify_token(token)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_create_and_verify_refresh_token(self):
        token = create_refresh_token(data={"sub": "user-123"})
        payload = verify_token(token, is_refresh=True)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self):
        token = create_access_token(data={"sub": "user-123"})
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, is_refresh=True)
        assert exc_info.value.status_code == 401

    def test_refresh_token_rejected_as_access(self):
        token = create_refresh_token(data={"sub": "user-123"})
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, is_refresh=False)
        assert exc_info.value.status_code == 401

    def test_expired_token(self):
        token = create_access_token(
            data={"sub": "user-123"},
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_invalid_token(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_token("not-a-real-token")
        assert exc_info.value.status_code == 401


# ============================================================
# Token Blacklist
# ============================================================

class TestTokenBlacklist:
    def test_blacklist_token(self):
        bl = TokenBlacklist()
        bl.add("token-abc", expires_at=time.time() + 3600)
        assert bl.is_blacklisted("token-abc") is True
        assert bl.is_blacklisted("token-xyz") is False

    def test_blacklisted_token_rejected(self):
        token = create_access_token(data={"sub": "user-123"})
        blacklist_token(token)
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()

    def test_cleanup_expired(self):
        bl = TokenBlacklist(cleanup_interval=0)  # Always cleanup
        bl.add("expired-token", expires_at=time.time() - 1)  # Already expired
        # Trigger cleanup by checking
        bl.is_blacklisted("some-other-token")
        assert bl.is_blacklisted("expired-token") is False


# ============================================================
# Validators
# ============================================================

class TestGSTINValidation:
    def test_valid_gstin(self):
        assert validate_gstin("27AAACM7890G1Z3") is True

    def test_invalid_gstin_short(self):
        assert validate_gstin("27AAA") is False

    def test_invalid_gstin_none(self):
        assert validate_gstin("") is False
        assert validate_gstin(None) is False


class TestPANValidation:
    def test_valid_pan(self):
        assert validate_pan("AABCS1234F") is True

    def test_invalid_pan_short(self):
        assert validate_pan("AABCS") is False

    def test_invalid_pan_format(self):
        assert validate_pan("1234567890") is False

    def test_invalid_pan_none(self):
        assert validate_pan("") is False
        assert validate_pan(None) is False
