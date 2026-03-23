# =============================================================
# GST Routes - DISABLED (stub only, no business logic yet)
# Uncomment and implement when GST service layer is built.
# =============================================================

# from fastapi import APIRouter, Depends, HTTPException, status
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
#
# router = APIRouter(prefix="/api/gst", tags=["GST"])
# security = HTTPBearer()
#
# @router.get("/filings", response_model=dict)
# async def get_gst_filings(
#     credentials: HTTPAuthorizationCredentials = Depends(security)
# ):
#     """Get GST filing history"""
#     return {
#         "success": True,
#         "data": []
#     }

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
