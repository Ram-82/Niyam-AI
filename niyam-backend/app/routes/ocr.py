# =============================================================
# OCR Routes - DISABLED (no OCR engine integrated yet)
# Uncomment and implement when pytesseract/OCR service is built.
# =============================================================

# from fastapi import APIRouter, UploadFile, File, Depends
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
#
# router = APIRouter(prefix="/api/ocr", tags=["OCR"])
# security = HTTPBearer()
#
# @router.post("/process")
# async def process_document(
#     file: UploadFile = File(...),
#     credentials: HTTPAuthorizationCredentials = Depends(security)
# ):
#     """Process uploaded document with OCR"""
#     pass

# Placeholder router so main.py imports don't break
from fastapi import APIRouter
router = APIRouter()
