# =============================================================
# TDS Routes - DISABLED (stub only, no business logic yet)
# Uncomment and implement when TDS service layer is built.
# =============================================================

# from fastapi import APIRouter
#
# router = APIRouter(prefix="/api/tds", tags=["TDS"])
#
# @router.get("/")
# async def get_tds():
#     return {"message": "TDS API"}

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
