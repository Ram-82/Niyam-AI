"""
File validation utilities — magic byte (file signature) verification.

Content-Type headers are client-supplied and trivially spoofable. Always
verify actual file content against known signatures before processing.
"""

from fastapi import HTTPException

# Magic byte signatures for each allowed MIME type.
# Format: mime_type -> list of (offset, signature_bytes) tuples.
# A file matches when ANY tuple's bytes appear at the given offset.
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "application/pdf": [
        (0, b"%PDF-"),
    ],
    "image/jpeg": [
        (0, b"\xff\xd8\xff"),
    ],
    "image/jpg": [
        (0, b"\xff\xd8\xff"),
    ],
    "image/png": [
        (0, b"\x89PNG\r\n\x1a\n"),
    ],
}


def verify_magic_bytes(content: bytes, claimed_mime: str) -> None:
    """
    Raise HTTP 400 if file content doesn't match the claimed MIME type.

    Args:
        content:      Raw file bytes (at least the first 16 bytes are enough).
        claimed_mime: The Content-Type the client declared.

    Raises:
        HTTPException(400): When the actual signature doesn't match.
    """
    signatures = _SIGNATURES.get(claimed_mime)
    if not signatures:
        # If we have no signature for this type it slipped past ALLOWED_MIME —
        # reject it to be safe.
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type.",
        )

    header = content[:16]
    for offset, sig in signatures:
        if header[offset: offset + len(sig)] == sig:
            return  # Valid

    raise HTTPException(
        status_code=400,
        detail=(
            "File content does not match the declared type. "
            "Ensure you are uploading a valid PDF, JPEG, or PNG."
        ),
    )


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """
    Return a filename safe for logging and HTTP Content-Disposition headers.

    Strips control characters and quotes that could enable header injection.
    Trims to max_length to prevent log flooding.
    """
    # Remove ASCII control characters (0x00-0x1f, 0x7f) and header-unsafe chars
    cleaned = "".join(
        c for c in filename
        if ord(c) >= 0x20 and c not in ('"', "'", "\\", "\r", "\n", "\0")
    )
    return cleaned[:max_length] or "document"
