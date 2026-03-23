# =============================================================
# Analytics Routes - DISABLED (stub only, no business logic yet)
# Uncomment and implement when analytics service is built.
# =============================================================

# from fastapi import APIRouter
#
# router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
#
# @router.get("/")
# async def get_analytics():
#     return {"message": "Analytics API"}

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
