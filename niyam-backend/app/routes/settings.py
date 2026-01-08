from fastapi import APIRouter

router = APIRouter(prefix="/api/settings", tags=["Settings"])

@router.get("/")
async def get_settings():
    return {"message": "Settings API"}
