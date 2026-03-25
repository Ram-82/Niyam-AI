"""
Middleware — rate limiting, request tracing, and error standardization.

Provides:
    1. Rate limiter (in-memory, per-IP) — for login, demo, and sensitive endpoints
    2. Request ID injection — every request gets a unique trace ID
    3. Standardized error handler — consistent { "error": ..., "code": ... } shape
"""

import time
import uuid
import logging
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ============================================================
# Rate Limiter (in-memory, per IP)
# ============================================================

class _RateBucket:
    """Sliding-window counter per IP per route pattern."""
    __slots__ = ("hits", "window_start")

    def __init__(self):
        self.hits = 0
        self.window_start = time.time()


class RateLimiter:
    """
    Simple in-memory rate limiter.

    Usage:
        limiter = RateLimiter()
        limiter.add_rule("/api/auth/login", max_requests=10, window_seconds=60)
        limiter.add_rule("/api/demo/run", max_requests=30, window_seconds=60)
    """

    def __init__(self):
        # route_prefix -> (max_requests, window_seconds)
        self._rules: Dict[str, Tuple[int, int]] = {}
        # (ip, route_prefix) -> _RateBucket
        self._buckets: Dict[Tuple[str, str], _RateBucket] = defaultdict(_RateBucket)

    def add_rule(self, route_prefix: str, max_requests: int, window_seconds: int):
        self._rules[route_prefix] = (max_requests, window_seconds)

    def check(self, ip: str, path: str) -> Tuple[bool, str]:
        """
        Returns (allowed, rule_matched).
        Resets window when expired. Returns (True, "") if no rule matches.
        """
        for prefix, (max_req, window) in self._rules.items():
            if path.startswith(prefix):
                key = (ip, prefix)
                bucket = self._buckets[key]
                now = time.time()

                # Reset window if expired
                if now - bucket.window_start >= window:
                    bucket.hits = 0
                    bucket.window_start = now

                bucket.hits += 1

                if bucket.hits > max_req:
                    return False, prefix

                return True, prefix

        return True, ""


# Global limiter instance
rate_limiter = RateLimiter()
rate_limiter.add_rule("/api/auth/login", max_requests=10, window_seconds=60)
rate_limiter.add_rule("/api/auth/signup", max_requests=5, window_seconds=60)
rate_limiter.add_rule("/api/demo/run", max_requests=30, window_seconds=60)
rate_limiter.add_rule("/api/upload", max_requests=20, window_seconds=60)
rate_limiter.add_rule("/api/extract", max_requests=20, window_seconds=60)
rate_limiter.add_rule("/api/itc-match", max_requests=15, window_seconds=60)
rate_limiter.add_rule("/api/process-invoice", max_requests=10, window_seconds=60)
rate_limiter.add_rule("/api/compliance-check", max_requests=20, window_seconds=60)
rate_limiter.add_rule("/api/export", max_requests=10, window_seconds=60)


# ============================================================
# Request ID Middleware
# ============================================================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Injects X-Request-ID into every request/response.
    Logs each request with the trace ID for end-to-end observability.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
        request.state.request_id = request_id

        # Log request start
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"client={request.client.host if request.client else 'unknown'}"
        )

        t0 = time.time()
        response = await call_next(request)
        elapsed_ms = round((time.time() - t0) * 1000)

        response.headers["X-Request-ID"] = request_id
        logger.info(f"[{request_id}] {response.status_code} ({elapsed_ms}ms)")

        return response


# ============================================================
# Rate Limit Middleware
# ============================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces per-IP rate limits on configured routes."""

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "0.0.0.0"
        path = request.url.path

        allowed, matched_rule = rate_limiter.check(ip, path)
        if not allowed:
            request_id = getattr(request.state, "request_id", "?")
            logger.warning(f"[{request_id}] Rate limit exceeded: {ip} on {matched_rule}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests. Please try again later.",
                    "code": "RATE_LIMIT_EXCEEDED",
                },
            )

        return await call_next(request)


# ============================================================
# Standardized Error Handler
# ============================================================

def install_error_handlers(app: FastAPI):
    """Install global exception handlers for consistent error shape."""

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", "unknown")
        errors = []
        for error in exc.errors():
            field = " → ".join(str(loc) for loc in error.get("loc", []))
            errors.append({
                "field": field,
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "validation_error"),
            })
        logger.warning(f"[{request_id}] Validation error: {errors}")
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation failed",
                "code": "VALIDATION_ERROR",
                "details": errors,
                "request_id": request_id,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail or "Request failed",
                "code": f"HTTP_{exc.status_code}",
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(f"[{request_id}] Unhandled error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
                "request_id": request_id,
            },
        )
