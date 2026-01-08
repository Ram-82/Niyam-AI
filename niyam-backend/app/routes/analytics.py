from fastapi import APIRouter

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.get("/")
async def get_analytics():
    return {"message": "Analytics API"}
