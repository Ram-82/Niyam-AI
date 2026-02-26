from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio

router = APIRouter(prefix="/api/ocr", tags=["OCR"])
security = HTTPBearer()

@router.post("/process", response_model=dict)
async def process_document(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Mock OCR processing for hackathon demo"""
    # Simulate processing delay
    await asyncio.sleep(2) 
    
    return {
        "success": True,
        "data": {
            "document_type": "GST Invoice",
            "extracted_data": {
                "gstin": "27AAACR1234A1Z1",
                "vendor_name": "Acme Industrial Supplies",
                "invoice_date": "2025-05-15",
                "total_amount": "₹1,24,000",
                "tax_amount": "₹18,915",
                "confidence_score": 0.98
            },
            "compliance_check": {
                "status": "Verified",
                "warnings": []
            }
        }
    }
