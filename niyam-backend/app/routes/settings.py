# =============================================================
# Settings Routes - DISABLED (stub only, no business logic yet)
# Uncomment and implement when settings service is built.
# =============================================================

# from fastapi import APIRouter
#
# router = APIRouter(prefix="/api/settings", tags=["Settings"])
#
# @router.get("/")
# async def get_settings():
#     return {"message": "Settings API"}

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
