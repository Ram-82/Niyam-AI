"""
Demo Routes — instant full-pipeline demo, no auth required.

GET /api/demo/run  → full pipeline output with trust layer
"""

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.demo_service import DemoService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/demo", tags=["Demo"])


@router.get("/run", response_class=JSONResponse)
async def run_demo(
    top_n: int = Query(3, ge=1, le=10, description="Number of top actions"),
):
    """
    Run the full Niyam AI pipeline on a prebuilt demo dataset.

    No authentication required. No upload needed. Runs in <2 seconds.

    Returns dashboard summary, ITC results, compliance flags,
    filing readiness, and trust layer (explanation + calculation + source)
    for every flag and match result.
    """
    service = DemoService()
    result = service.run(top_n=top_n)

    return {
        "success": True,
        "data": result,
    }
