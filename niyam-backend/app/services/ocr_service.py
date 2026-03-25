"""
OCR Service — Production-grade text extraction from PDFs and images.

Pipeline:
1. pdfplumber for native/digital PDFs (fast, accurate, table-aware)
2. OpenCV preprocessing for scanned documents:
   - Grayscale conversion
   - Adaptive thresholding
   - Denoising (Non-local Means)
   - Skew correction (Hough transform)
3. pytesseract for scanned PDFs and images (with preprocessed input)
4. Structure detection:
   - Table detection via pdfplumber or contour analysis
   - Line grouping and bounding boxes
   - Block-level output with type annotations

Output format:
{
    "raw_text": "...",
    "blocks": [
        {"text": "...", "bbox": [x0, y0, x1, y1], "type": "line|table|header"}
    ],
    "tables": [
        {"headers": [...], "rows": [[...], ...], "bbox": [x0, y0, x1, y1]}
    ],
    "method": "pdfplumber|tesseract|hybrid",
    "page_count": int,
    "char_count": int,
    "quality": "good|partial|poor|empty",
    "confidence": 0-100
}
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# Image Preprocessing (OpenCV)
# ============================================================

class ImagePreprocessor:
    """OpenCV-based image preprocessing for OCR quality improvement."""

    def __init__(self):
        self._cv2 = None

    @property
    def cv2(self):
        if self._cv2 is None:
            try:
                import cv2
                self._cv2 = cv2
            except ImportError:
                logger.warning("OpenCV (cv2) not installed — preprocessing disabled.")
                self._cv2 = False
        return self._cv2 if self._cv2 is not False else None

    def preprocess(self, image) -> "np.ndarray":
        """
        Full preprocessing pipeline for OCR:
        1. Convert to grayscale
        2. Denoise
        3. Skew correction
        4. Adaptive thresholding

        Args:
            image: PIL Image or numpy array

        Returns:
            Preprocessed numpy array (grayscale, uint8)
        """
        cv2 = self.cv2
        if cv2 is None:
            # Fallback: return image as-is (numpy array from PIL)
            return np.array(image)

        # Convert PIL Image to numpy array if needed
        img = np.array(image)

        # Step 1: Grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img.copy()

        # Step 2: Denoise (Non-local Means Denoising)
        denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

        # Step 3: Skew correction
        corrected = self._correct_skew(denoised)

        # Step 4: Adaptive thresholding (handles uneven lighting)
        thresh = cv2.adaptiveThreshold(
            corrected, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )

        return thresh

    def _correct_skew(self, gray: "np.ndarray") -> "np.ndarray":
        """Detect and correct document skew using Hough Line Transform."""
        cv2 = self.cv2
        if cv2 is None:
            return gray

        try:
            # Edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)

            # Hough Line Transform
            lines = cv2.HoughLinesP(
                edges, 1, np.pi / 180,
                threshold=100, minLineLength=100, maxLineGap=10,
            )

            if lines is None or len(lines) == 0:
                return gray

            # Calculate median angle from detected lines
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Only consider near-horizontal lines (within 15 degrees)
                if abs(angle) < 15:
                    angles.append(angle)

            if not angles:
                return gray

            median_angle = np.median(angles)

            # Only correct if skew is significant (> 0.5 degree)
            if abs(median_angle) < 0.5:
                return gray

            # Rotate to correct skew
            h, w = gray.shape[:2]
            center = (w // 2, h // 2)
            rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            corrected = cv2.warpAffine(
                gray, rotation_matrix, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

            logger.debug(f"Skew corrected: {median_angle:.2f} degrees")
            return corrected

        except Exception as e:
            logger.debug(f"Skew correction failed (non-critical): {e}")
            return gray

    def detect_table_regions(self, gray: "np.ndarray") -> List[dict]:
        """
        Detect table-like regions using contour analysis.
        Returns list of bounding boxes for detected tables.
        """
        cv2 = self.cv2
        if cv2 is None:
            return []

        try:
            # Binary threshold
            _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

            # Detect horizontal lines
            h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
            h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

            # Detect vertical lines
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
            v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

            # Combine
            table_mask = cv2.add(h_lines, v_lines)

            # Find contours of table regions
            contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            tables = []
            img_area = gray.shape[0] * gray.shape[1]

            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h
                # Filter: table must be reasonably sized (>1% of image, <90%)
                if area > img_area * 0.01 and area < img_area * 0.9:
                    tables.append({
                        "bbox": [int(x), int(y), int(x + w), int(y + h)],
                        "area": int(area),
                    })

            # Sort by position (top to bottom)
            tables.sort(key=lambda t: t["bbox"][1])
            return tables

        except Exception as e:
            logger.debug(f"Table detection failed (non-critical): {e}")
            return []


# ============================================================
# Structure Detection
# ============================================================

def _extract_blocks_from_words(words: list, page_height: float = 0) -> List[dict]:
    """
    Group pdfplumber words into line-level blocks with bounding boxes.
    Words on the same Y-coordinate (within tolerance) form a line.
    """
    if not words:
        return []

    # Sort words by vertical position, then horizontal
    sorted_words = sorted(words, key=lambda w: (round(float(w.get("top", 0)) / 3), float(w.get("x0", 0))))

    blocks = []
    current_line_words = [sorted_words[0]]
    current_top = float(sorted_words[0].get("top", 0))

    for word in sorted_words[1:]:
        word_top = float(word.get("top", 0))
        # Same line if within 3 points vertically
        if abs(word_top - current_top) < 3:
            current_line_words.append(word)
        else:
            # Flush current line
            blocks.append(_words_to_block(current_line_words))
            current_line_words = [word]
            current_top = word_top

    # Flush last line
    if current_line_words:
        blocks.append(_words_to_block(current_line_words))

    return blocks


def _words_to_block(words: list) -> dict:
    """Convert a list of words into a single block with bbox."""
    text = " ".join(w.get("text", "") for w in words)
    x0 = min(float(w.get("x0", 0)) for w in words)
    y0 = min(float(w.get("top", 0)) for w in words)
    x1 = max(float(w.get("x1", 0)) for w in words)
    y1 = max(float(w.get("bottom", 0)) for w in words)

    # Classify block type
    block_type = "line"
    text_stripped = text.strip()
    if len(text_stripped) < 50 and text_stripped.isupper():
        block_type = "header"

    return {
        "text": text_stripped,
        "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
        "type": block_type,
    }


def _extract_tables_pdfplumber(page) -> List[dict]:
    """Extract tables from a pdfplumber page with headers and rows."""
    tables = []
    try:
        raw_tables = page.extract_tables()
        if not raw_tables:
            return []

        for table in raw_tables:
            if not table or len(table) < 2:
                continue

            # First row as headers, rest as data
            headers = [str(cell).strip() if cell else "" for cell in table[0]]
            rows = []
            for row in table[1:]:
                cleaned_row = [str(cell).strip() if cell else "" for cell in row]
                # Skip empty rows
                if any(cell for cell in cleaned_row):
                    rows.append(cleaned_row)

            if headers and rows:
                tables.append({
                    "headers": headers,
                    "rows": rows,
                    "bbox": [],  # pdfplumber doesn't give table bbox easily
                })

    except Exception as e:
        logger.debug(f"Table extraction failed: {e}")

    return tables


# ============================================================
# Main OCR Service
# ============================================================

class OCRService:
    """Production-grade OCR with preprocessing, structure detection, and quality assessment."""

    def __init__(self):
        self._tesseract_available = None
        self._pdfplumber_available = None
        self._preprocessor = ImagePreprocessor()

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
        Extract text with structure detection.

        Returns structured output:
        {
            "text": "full raw text",
            "raw_text": "full raw text (alias)",
            "blocks": [{"text": ..., "bbox": [...], "type": "line|table|header"}],
            "tables": [{"headers": [...], "rows": [[...]], "bbox": [...]}],
            "method": "pdfplumber|tesseract|hybrid|none",
            "page_count": int,
            "char_count": int,
            "quality": "good|partial|poor|empty",
            "confidence": 0-100
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
            logger.error(f"OCR extraction failed: {e}", exc_info=True)
            return self._empty_result(str(e))

    async def _extract_from_pdf(self, file_path: str) -> dict:
        """
        Multi-strategy PDF extraction:
        1. pdfplumber for native text + tables + word-level blocks
        2. Tesseract fallback with OpenCV preprocessing for scanned PDFs
        3. Hybrid: combine both if pdfplumber text is sparse
        """
        text = ""
        blocks = []
        tables = []
        page_count = 0
        method = "none"
        confidence = 0

        # Strategy 1: pdfplumber (native PDF text + structure)
        if self.pdfplumber_available:
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    page_count = len(pdf.pages)
                    all_text_parts = []

                    for page in pdf.pages:
                        # Extract text
                        page_text = page.extract_text() or ""
                        all_text_parts.append(page_text)

                        # Extract word-level blocks for structure
                        words = page.extract_words() or []
                        page_blocks = _extract_blocks_from_words(words, page.height)
                        blocks.extend(page_blocks)

                        # Extract tables
                        page_tables = _extract_tables_pdfplumber(page)
                        tables.extend(page_tables)

                        # Mark table blocks
                        for table in page_tables:
                            table_text = " | ".join(table["headers"])
                            for row in table["rows"]:
                                table_text += "\n" + " | ".join(row)
                            blocks.append({
                                "text": table_text,
                                "bbox": table.get("bbox", []),
                                "type": "table",
                            })

                    text = "\n\n".join(all_text_parts)
                    method = "pdfplumber"
                    confidence = 85

            except Exception as e:
                logger.warning(f"pdfplumber failed: {e}")

        # Strategy 2: If pdfplumber yielded too little text, try tesseract with preprocessing
        if len(text.strip()) < 50 and self.tesseract_available:
            logger.info("pdfplumber extracted minimal text, trying tesseract with preprocessing...")
            try:
                tess_result = await self._tesseract_pdf_with_preprocessing(file_path)
                tess_text = tess_result.get("text", "")

                if len(tess_text) > len(text):
                    text = tess_text
                    page_count = tess_result.get("page_count", page_count)
                    method = "tesseract"
                    confidence = tess_result.get("confidence", 60)

                    # Merge blocks from tesseract
                    if tess_result.get("blocks"):
                        blocks = tess_result["blocks"]
                    if tess_result.get("tables"):
                        tables = tess_result["tables"]

            except Exception as e:
                logger.warning(f"Tesseract PDF fallback failed: {e}")

        # Strategy 3: Hybrid — supplement pdfplumber with tesseract for low-confidence pages
        elif 50 <= len(text.strip()) < 200 and self.tesseract_available:
            try:
                tess_result = await self._tesseract_pdf_with_preprocessing(file_path)
                tess_text = tess_result.get("text", "")
                if len(tess_text) > len(text) * 1.5:
                    text = tess_text
                    method = "hybrid"
                    confidence = max(confidence, tess_result.get("confidence", 50))
            except Exception:
                pass  # pdfplumber result is still usable

        quality = self._assess_quality(text)

        # Adjust confidence based on quality
        if quality == "good" and confidence < 70:
            confidence = 75
        elif quality == "poor":
            confidence = min(confidence, 40)
        elif quality == "empty":
            confidence = 0

        return {
            "text": text.strip(),
            "raw_text": text.strip(),
            "blocks": blocks,
            "tables": tables,
            "method": method,
            "page_count": page_count,
            "char_count": len(text.strip()),
            "quality": quality,
            "confidence": confidence,
        }

    async def _extract_from_image(self, file_path: str) -> dict:
        """Extract text from an image with OpenCV preprocessing."""
        if not self.tesseract_available:
            return self._empty_result("Tesseract not available for image OCR")

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)

            # Preprocess with OpenCV
            preprocessed = self._preprocessor.preprocess(img)

            # Convert preprocessed numpy array back to PIL for pytesseract
            from PIL import Image as PILImage
            if isinstance(preprocessed, np.ndarray):
                processed_img = PILImage.fromarray(preprocessed)
            else:
                processed_img = img

            # OCR with language support
            try:
                text = pytesseract.image_to_string(processed_img, lang="eng+hin")
            except Exception:
                text = pytesseract.image_to_string(processed_img, lang="eng")

            # Get word-level data for blocks
            blocks = []
            try:
                data = pytesseract.image_to_data(processed_img, output_type=pytesseract.Output.DICT)
                blocks = self._tesseract_data_to_blocks(data)
            except Exception:
                # Fallback: create blocks from lines
                for i, line in enumerate(text.split("\n")):
                    line = line.strip()
                    if line:
                        blocks.append({
                            "text": line,
                            "bbox": [],
                            "type": "line",
                        })

            # Detect tables from image
            tables = []
            gray = np.array(img.convert("L")) if img.mode != "L" else np.array(img)
            table_regions = self._preprocessor.detect_table_regions(gray)
            if table_regions:
                for region in table_regions:
                    # Mark as table block
                    blocks.append({
                        "text": "[table region detected]",
                        "bbox": region["bbox"],
                        "type": "table",
                    })

            # Calculate confidence from tesseract
            confidence = self._calculate_tesseract_confidence(processed_img)

            return {
                "text": text.strip(),
                "raw_text": text.strip(),
                "blocks": blocks,
                "tables": tables,
                "method": "tesseract",
                "page_count": 1,
                "char_count": len(text.strip()),
                "quality": self._assess_quality(text),
                "confidence": confidence,
            }
        except Exception as e:
            logger.error(f"Image OCR failed: {e}", exc_info=True)
            return self._empty_result(str(e))

    async def _tesseract_pdf_with_preprocessing(self, file_path: str) -> dict:
        """Convert PDF pages to images, preprocess with OpenCV, then OCR."""
        import pytesseract
        from pdf2image import convert_from_path
        from PIL import Image as PILImage

        images = convert_from_path(file_path, dpi=300)
        pages_text = []
        all_blocks = []
        total_confidence = 0

        for page_num, img in enumerate(images):
            try:
                # OpenCV preprocessing
                preprocessed = self._preprocessor.preprocess(img)

                if isinstance(preprocessed, np.ndarray):
                    processed_img = PILImage.fromarray(preprocessed)
                else:
                    processed_img = img

                # OCR
                page_text = pytesseract.image_to_string(processed_img, lang="eng")
                pages_text.append(page_text)

                # Word-level data for blocks
                try:
                    data = pytesseract.image_to_data(processed_img, output_type=pytesseract.Output.DICT)
                    page_blocks = self._tesseract_data_to_blocks(data)
                    all_blocks.extend(page_blocks)
                except Exception:
                    for line in page_text.split("\n"):
                        line = line.strip()
                        if line:
                            all_blocks.append({"text": line, "bbox": [], "type": "line"})

                # Page confidence
                total_confidence += self._calculate_tesseract_confidence(processed_img)

            except Exception as e:
                logger.warning(f"Tesseract page {page_num} OCR failed: {e}")
                pages_text.append("")

        text = "\n\n".join(pages_text)
        avg_confidence = int(total_confidence / len(images)) if images else 0

        return {
            "text": text.strip(),
            "blocks": all_blocks,
            "tables": [],
            "page_count": len(images),
            "confidence": avg_confidence,
        }

    def _tesseract_data_to_blocks(self, data: dict) -> List[dict]:
        """Convert pytesseract word-level data into line blocks."""
        blocks = []
        n_words = len(data.get("text", []))

        # Group words by line number
        lines = {}
        for i in range(n_words):
            text = data["text"][i].strip()
            if not text:
                continue

            line_num = data.get("line_num", [0] * n_words)[i]
            block_num = data.get("block_num", [0] * n_words)[i]
            key = (block_num, line_num)

            if key not in lines:
                lines[key] = {
                    "words": [],
                    "x0": float("inf"),
                    "y0": float("inf"),
                    "x1": 0,
                    "y1": 0,
                }

            lines[key]["words"].append(text)

            x = data.get("left", [0] * n_words)[i]
            y = data.get("top", [0] * n_words)[i]
            w = data.get("width", [0] * n_words)[i]
            h = data.get("height", [0] * n_words)[i]

            lines[key]["x0"] = min(lines[key]["x0"], x)
            lines[key]["y0"] = min(lines[key]["y0"], y)
            lines[key]["x1"] = max(lines[key]["x1"], x + w)
            lines[key]["y1"] = max(lines[key]["y1"], y + h)

        # Convert to blocks
        for key in sorted(lines.keys()):
            line_data = lines[key]
            line_text = " ".join(line_data["words"])
            if line_text.strip():
                block_type = "header" if line_text.isupper() and len(line_text) < 60 else "line"
                blocks.append({
                    "text": line_text,
                    "bbox": [
                        line_data["x0"], line_data["y0"],
                        line_data["x1"], line_data["y1"],
                    ],
                    "type": block_type,
                })

        return blocks

    def _calculate_tesseract_confidence(self, image) -> int:
        """Get average OCR confidence from tesseract."""
        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data.get("conf", []) if int(c) > 0]
            if confidences:
                return int(sum(confidences) / len(confidences))
        except Exception:
            pass
        return 50  # default moderate confidence

    def _assess_quality(self, text: str) -> str:
        """Assess OCR text quality."""
        text = text.strip()
        if not text:
            return "empty"
        if len(text) < 100:
            return "poor"
        # Check for garbled text
        printable_ratio = sum(1 for c in text if c.isprintable()) / len(text)
        if printable_ratio < 0.7:
            return "poor"
        if printable_ratio < 0.85:
            return "partial"
        return "good"

    def _empty_result(self, error: str = "") -> dict:
        return {
            "text": "",
            "raw_text": "",
            "blocks": [],
            "tables": [],
            "method": "none",
            "page_count": 0,
            "char_count": 0,
            "quality": "empty",
            "confidence": 0,
            "error": error,
        }
