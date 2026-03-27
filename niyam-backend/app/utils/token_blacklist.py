"""
In-memory token blacklist with automatic TTL-based cleanup.

Tokens are stored with their expiry time. Expired entries are pruned
periodically to prevent unbounded memory growth. In production, this
should be replaced with Redis for persistence across restarts and
multi-process deployments.
"""

import threading
import time
from typing import Optional


class TokenBlacklist:
    """Thread-safe in-memory token blacklist."""

    def __init__(self, cleanup_interval: int = 300):
        self._blacklisted: dict[str, float] = {}  # token_jti_or_raw -> expiry_timestamp
        self._lock = threading.Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def add(self, token: str, expires_at: Optional[float] = None):
        """
        Blacklist a token.

        Args:
            token: The raw JWT string (or its jti claim).
            expires_at: Unix timestamp when the token expires.
                        If None, defaults to 24 hours from now.
        """
        if expires_at is None:
            expires_at = time.time() + 86400  # 24 hours default

        with self._lock:
            self._blacklisted[token] = expires_at
            self._maybe_cleanup()

    def is_blacklisted(self, token: str) -> bool:
        """Check if a token has been blacklisted."""
        with self._lock:
            self._maybe_cleanup()
            if token in self._blacklisted:
                # Still valid blacklist entry (hasn't expired from blacklist)
                return True
            return False

    def _maybe_cleanup(self):
        """Remove expired tokens from the blacklist (called under lock)."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        expired_keys = [
            k for k, exp in self._blacklisted.items() if exp < now
        ]
        for k in expired_keys:
            del self._blacklisted[k]


# Global singleton
token_blacklist = TokenBlacklist()
