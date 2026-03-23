from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class DocumentType(str, Enum):
    PURCHASE_INVOICE = "purchase_invoice"
    SALES_INVOICE = "sales_invoice"
    BANK_STATEMENT = "bank_statement"
    GSTR2B = "gstr2b"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    FAILED = "failed"


class DocumentResponse(BaseModel):
    id: str
    business_id: str
    filename: str
    document_type: DocumentType
    status: DocumentStatus
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExtractedFieldOut(BaseModel):
    """A single extracted field with confidence score."""
    value: Optional[object] = None
    confidence: int = Field(0, ge=0, le=100)
    method: Optional[str] = None


class ExtractionResult(BaseModel):
    """Full extraction result from OCR + parser."""
    document_id: str
    status: str  # "extracted" or "failed"
    ocr_quality: str  # "good", "partial", "poor", "empty"
    ocr_method: str  # "pdfplumber", "tesseract", "none"

    gstin: ExtractedFieldOut
    invoice_number: ExtractedFieldOut
    invoice_date: ExtractedFieldOut
    vendor_name: ExtractedFieldOut
    taxable_amount: ExtractedFieldOut
    cgst: ExtractedFieldOut
    sgst: ExtractedFieldOut
    igst: ExtractedFieldOut
    gst_amount: ExtractedFieldOut
    total_amount: ExtractedFieldOut
    hsn_codes: ExtractedFieldOut

    overall_confidence: int = 0
    needs_review: List[str] = []
    extraction_errors: List[str] = []


class ExtractRequest(BaseModel):
    document_id: str
