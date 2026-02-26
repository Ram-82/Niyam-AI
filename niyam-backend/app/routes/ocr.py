from fastapi import APIRouter

router = APIRouter(prefix="/api/ocr", tags=["OCR"])

@router.get("/")
async def get_ocr():
    return {"message": "OCR API"}
