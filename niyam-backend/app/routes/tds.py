from fastapi import APIRouter

router = APIRouter(prefix="/api/tds", tags=["TDS"])

@router.get("/")
async def get_tds():
    return {"message": "TDS API"}
