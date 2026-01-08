from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# from app.services.gst_service import GSTService # To be implemented

router = APIRouter(prefix="/api/gst", tags=["GST"])
security = HTTPBearer()

@router.get("/filings", response_model=dict)
async def get_gst_filings(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get GST filing history"""
    return {
        "success": True,
        "data": []
    }
