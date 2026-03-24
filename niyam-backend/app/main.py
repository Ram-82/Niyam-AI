from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.config import settings
from app.middleware import RequestIDMiddleware, RateLimitMiddleware, install_error_handlers
from app.routes import (
    auth, dashboard, upload, compliance, gst, tds, roc,
    ocr, analytics, export, demo, settings as settings_routes
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
    yield
    logger.info("Shutting down Niyam AI Compliance OS API...")


# Create FastAPI app
app = FastAPI(
    title="Niyam AI Compliance OS API",
    description="Backend API for Indian MSME Compliance Management",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Middleware stack (order matters — outermost first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)

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
app.include_router(demo.router)
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
