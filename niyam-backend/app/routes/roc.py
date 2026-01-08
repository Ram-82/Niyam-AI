from fastapi import APIRouter

router = APIRouter(prefix="/api/roc", tags=["ROC"])

@router.get("/")
async def get_roc():
    return {"message": "ROC API"}
