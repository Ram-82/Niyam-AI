"""
Email Verification — generate and validate 6-digit verification codes.

Uses an in-memory store with TTL (like token_blacklist pattern).
Production should replace with Redis or DB-backed storage + real email sending.
"""

import logging
import random
import string
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# TTL for verification codes (10 minutes)
CODE_TTL = 600
# Max attempts before lockout
MAX_ATTEMPTS = 5


class VerificationStore:
    """In-memory store for verification codes with TTL and attempt tracking."""

    def __init__(self):
        self._codes: dict[str, dict] = {}  # email -> {code, expires_at, attempts}
        self._lock = threading.Lock()

    def generate(self, email: str) -> str:
        """Generate a 6-digit code for the given email."""
        code = ''.join(random.choices(string.digits, k=6))
        with self._lock:
            self._codes[email.lower()] = {
                "code": code,
                "expires_at": time.time() + CODE_TTL,
                "attempts": 0,
            }
        self._cleanup()
        return code

    def verify(self, email: str, code: str) -> Tuple[bool, str]:
        """
        Verify a code for the given email.
        Returns (success, message).
        """
        email_lower = email.lower()
        with self._lock:
            entry = self._codes.get(email_lower)
            if not entry:
                return False, "No verification code found. Please request a new one."

            if time.time() > entry["expires_at"]:
                del self._codes[email_lower]
                return False, "Verification code expired. Please request a new one."

            if entry["attempts"] >= MAX_ATTEMPTS:
                del self._codes[email_lower]
                return False, "Too many failed attempts. Please request a new code."

            if entry["code"] != code.strip():
                entry["attempts"] += 1
                remaining = MAX_ATTEMPTS - entry["attempts"]
                return False, f"Invalid code. {remaining} attempts remaining."

            # Success — remove the code
            del self._codes[email_lower]
            return True, "Email verified successfully."

    def get_code_for_display(self, email: str) -> Optional[str]:
        """
        Get the current code for display (development mode only).
        In production, this should be removed and codes sent via email.
        """
        email_lower = email.lower()
        with self._lock:
            entry = self._codes.get(email_lower)
            if entry and time.time() <= entry["expires_at"]:
                return entry["code"]
        return None

    def _cleanup(self):
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._codes.items() if now > v["expires_at"]]
            for k in expired:
                del self._codes[k]


# Singleton instance
verification_store = VerificationStore()

# Separate store for password reset codes (same mechanics, isolated namespace)
password_reset_store = VerificationStore()
