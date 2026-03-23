# =============================================================
# ROC Routes - DISABLED (stub only, no business logic yet)
# Uncomment and implement when ROC service layer is built.
# =============================================================

# from fastapi import APIRouter
#
# router = APIRouter(prefix="/api/roc", tags=["ROC"])
#
# @router.get("/")
# async def get_roc():
#     return {"message": "ROC API"}

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
