from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.config import settings
from app.middleware import RequestIDMiddleware, RateLimitMiddleware, install_error_handlers
from app.routes import (
    auth, dashboard, upload, compliance, gst, tds, roc,
    ocr, analytics, export, demo, itc, process_invoice, invoices, audit,
    onboarding, payments, settings as settings_routes
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info(f"Starting Niyam AI Compliance OS API (env={settings.ENVIRONMENT})")

    # Start the deadline reminder scheduler (daily 8 AM IST)
    from app.services.scheduler import deadline_scheduler
    deadline_scheduler.start()

    yield

    deadline_scheduler.shutdown()
    logger.info("Shutting down Niyam AI Compliance OS API...")


# Disable interactive docs in production — they expose the full API surface.
_docs_url = None if settings.ENVIRONMENT == "production" else "/api/docs"
_redoc_url = None if settings.ENVIRONMENT == "production" else "/api/redoc"
_openapi_url = None if settings.ENVIRONMENT == "production" else "/api/openapi.json"

# Create FastAPI app
app = FastAPI(
    title="Niyam AI Compliance OS API",
    description="Backend API for Indian MSME Compliance Management",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    lifespan=lifespan,
)

# Middleware stack — Starlette wraps in LIFO order (last added = outermost = first to run).
# Correct request flow: CORS → RateLimit → RequestID → route handler
# CORS must be outermost so that browser preflight (OPTIONS) requests receive
# CORS headers even when they are rejected by rate limiting.
app.add_middleware(RequestIDMiddleware)   # innermost — runs last on request
app.add_middleware(RateLimitMiddleware)   # middle
app.add_middleware(                       # outermost — runs first on request
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=settings.ALLOWED_ORIGINS != ["*"],  # credentials require explicit origin
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# Standardized error handlers
install_error_handlers(app)

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(upload.router)
app.include_router(compliance.router)
app.include_router(gst.router)
app.include_router(tds.router)
app.include_router(roc.router)
app.include_router(ocr.router)
app.include_router(analytics.router)
app.include_router(export.router)
app.include_router(itc.router)
app.include_router(process_invoice.router)
app.include_router(invoices.router)
app.include_router(audit.router)
app.include_router(onboarding.router)
app.include_router(demo.router)
app.include_router(payments.router)
app.include_router(settings_routes.router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Niyam AI Compliance OS API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "status": "operational",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health")
async def health_check():
    from app.database import test_connection

    db_ok = test_connection() if settings.ENVIRONMENT == "production" else True

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )
