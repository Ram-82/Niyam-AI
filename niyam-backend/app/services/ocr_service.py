"""
OCR Service — Extract raw text from PDFs and images.

Strategies (in order):
1. pdfplumber for native/text-based PDFs (fast, accurate)
2. pytesseract for scanned PDFs and images (slower, handles photos)

Does NOT parse or interpret. Just returns raw text.
"""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class OCRService:
    """Extract raw text from uploaded documents."""

    def __init__(self):
        self._tesseract_available = None
        self._pdfplumber_available = None

    @property
    def tesseract_available(self) -> bool:
        if self._tesseract_available is None:
            try:
                import pytesseract
                from app.config import settings
                pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_PATH
                pytesseract.get_tesseract_version()
                self._tesseract_available = True
            except Exception:
                self._tesseract_available = False
                logger.warning("Tesseract not available — image OCR disabled.")
        return self._tesseract_available

    @property
    def pdfplumber_available(self) -> bool:
        if self._pdfplumber_available is None:
            try:
                import pdfplumber  # noqa: F401
                self._pdfplumber_available = True
            except ImportError:
                self._pdfplumber_available = False
                logger.warning("pdfplumber not installed — PDF text extraction disabled.")
        return self._pdfplumber_available

    async def extract_text(self, file_path: str, mime_type: str) -> dict:
        """
        Extract text from a file. Returns:
        {
            "text": "...",
            "method": "pdfplumber" | "tesseract" | "none",
            "page_count": int,
            "char_count": int,
            "quality": "good" | "partial" | "poor" | "empty"
        }
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return self._empty_result("File not found")

        try:
            if mime_type == "application/pdf":
                return await self._extract_from_pdf(file_path)
            elif mime_type in ("image/jpeg", "image/png", "image/jpg"):
                return await self._extract_from_image(file_path)
            else:
                logger.warning(f"Unsupported mime type: {mime_type}")
                return self._empty_result(f"Unsupported file type: {mime_type}")
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return self._empty_result(str(e))

    async def _extract_from_pdf(self, file_path: str) -> dict:
        """
        Try pdfplumber first (native text). If that yields little text,
        fall back to tesseract (scanned PDF).
        """
        text = ""
        page_count = 0
        method = "none"

        # Strategy 1: pdfplumber (native PDF text)
        if self.pdfplumber_available:
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    page_count = len(pdf.pages)
                    pages_text = []
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        pages_text.append(page_text)
                    text = "\n\n".join(pages_text)
                    method = "pdfplumber"
            except Exception as e:
                logger.warning(f"pdfplumber failed: {e}")

        # If pdfplumber yielded too little text, try tesseract
        if len(text.strip()) < 50 and self.tesseract_available:
            logger.info("pdfplumber extracted minimal text, trying tesseract...")
            try:
                tess_result = await self._tesseract_pdf(file_path)
                if len(tess_result.get("text", "")) > len(text):
                    text = tess_result["text"]
                    page_count = tess_result.get("page_count", page_count)
                    method = "tesseract"
            except Exception as e:
                logger.warning(f"Tesseract PDF fallback failed: {e}")

        return {
            "text": text.strip(),
            "method": method,
            "page_count": page_count,
            "char_count": len(text.strip()),
            "quality": self._assess_quality(text),
        }

    async def _extract_from_image(self, file_path: str) -> dict:
        """Extract text from an image using tesseract."""
        if not self.tesseract_available:
            return self._empty_result("Tesseract not available for image OCR")

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            # Use Indian language support if available, fall back to English
            try:
                text = pytesseract.image_to_string(img, lang="eng+hin")
            except Exception:
                text = pytesseract.image_to_string(img, lang="eng")

            return {
                "text": text.strip(),
                "method": "tesseract",
                "page_count": 1,
                "char_count": len(text.strip()),
                "quality": self._assess_quality(text),
            }
        except Exception as e:
            logger.error(f"Image OCR failed: {e}")
            return self._empty_result(str(e))

    async def _tesseract_pdf(self, file_path: str) -> dict:
        """Convert PDF pages to images and OCR each page."""
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(file_path, dpi=300)
        pages_text = []
        for img in images:
            try:
                page_text = pytesseract.image_to_string(img, lang="eng")
                pages_text.append(page_text)
            except Exception as e:
                logger.warning(f"Tesseract page OCR failed: {e}")
                pages_text.append("")

        text = "\n\n".join(pages_text)
        return {"text": text.strip(), "page_count": len(images)}

    def _assess_quality(self, text: str) -> str:
        """Rough quality assessment of extracted text."""
        text = text.strip()
        if not text:
            return "empty"
        if len(text) < 100:
            return "poor"
        # Check for garbled text (high ratio of non-ascii or special chars)
        printable_ratio = sum(1 for c in text if c.isprintable()) / len(text)
        if printable_ratio < 0.7:
            return "poor"
        if printable_ratio < 0.85:
            return "partial"
        return "good"

    def _empty_result(self, error: str = "") -> dict:
        return {
            "text": "",
            "method": "none",
            "page_count": 0,
            "char_count": 0,
            "quality": "empty",
            "error": error,
        }
