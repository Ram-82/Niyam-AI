"""
Storage Service — persistent file storage for uploaded documents.

Production: Supabase Storage bucket (files survive server restarts).
Development: local uploads/ directory (same behaviour as before).

All file paths stored in the DB use a logical key:
    business/{business_id}/{timestamp}_{filename}
This key is used as the Supabase Storage object path *and* as the
relative path under uploads/ in dev mode.
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Local upload dir for dev mode
_LOCAL_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
_LOCAL_UPLOAD_DIR.mkdir(exist_ok=True)


class StorageService:
    """Upload, download, and delete files via Supabase Storage or local disk."""

    def __init__(self):
        self._supabase = None
        if settings.ENVIRONMENT == "production" and settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                from app.database import get_db_client
                self._supabase = get_db_client()
                if self._supabase:
                    logger.info(f"Storage: Supabase bucket '{settings.SUPABASE_STORAGE_BUCKET}'")
            except Exception as e:
                logger.warning(f"Storage: Supabase init failed, falling back to local: {e}")

    @property
    def _bucket(self):
        return settings.SUPABASE_STORAGE_BUCKET

    @property
    def is_remote(self) -> bool:
        return self._supabase is not None

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------
    @staticmethod
    def build_storage_key(business_id: str, filename: str) -> str:
        """Build a logical storage key: business/<bid>/<ts>_<name>."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return f"business/{business_id}/{ts}_{safe_name}"

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def upload(self, storage_key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        """Store file content. Returns the storage_key on success."""
        if self.is_remote:
            return self._upload_remote(storage_key, content, content_type)
        return self._upload_local(storage_key, content)

    def _upload_remote(self, key: str, content: bytes, content_type: str) -> str:
        try:
            self._supabase.storage.from_(self._bucket).upload(
                key, content, {"content-type": content_type}
            )
            logger.info(f"Storage: uploaded {key} ({len(content)} bytes) to Supabase")
            return key
        except Exception as e:
            logger.error(f"Storage: Supabase upload failed for {key}: {e}")
            raise RuntimeError(f"Storage upload failed: {e}")

    def _upload_local(self, key: str, content: bytes) -> str:
        path = _LOCAL_UPLOAD_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        logger.info(f"Storage: saved {key} ({len(content)} bytes) to local disk")
        return key

    # ------------------------------------------------------------------
    # Download (returns bytes)
    # ------------------------------------------------------------------
    def download(self, storage_key: str) -> bytes:
        """Retrieve file content by storage key."""
        if self.is_remote:
            return self._download_remote(storage_key)
        return self._download_local(storage_key)

    def _download_remote(self, key: str) -> bytes:
        try:
            data = self._supabase.storage.from_(self._bucket).download(key)
            return data
        except Exception as e:
            logger.error(f"Storage: Supabase download failed for {key}: {e}")
            raise RuntimeError(f"Storage download failed: {e}")

    def _download_local(self, key: str) -> bytes:
        path = _LOCAL_UPLOAD_DIR / key
        if not path.exists():
            raise FileNotFoundError(f"Local file not found: {key}")
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Download to temp file (for OCR which needs a filesystem path)
    # ------------------------------------------------------------------
    def download_to_temp(self, storage_key: str, suffix: str = "") -> str:
        """Download to a temp file and return its path. Caller must delete."""
        content = self.download(storage_key)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(content)
        tmp.close()
        return tmp.name

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete(self, storage_key: str):
        """Delete a file from storage. Errors are logged, not raised."""
        if self.is_remote:
            try:
                self._supabase.storage.from_(self._bucket).remove([storage_key])
                logger.info(f"Storage: deleted {storage_key} from Supabase")
            except Exception as e:
                logger.warning(f"Storage: Supabase delete failed for {storage_key}: {e}")
        else:
            path = _LOCAL_UPLOAD_DIR / storage_key
            if path.exists():
                path.unlink()
                logger.info(f"Storage: deleted {storage_key} from local disk")

    # ------------------------------------------------------------------
    # Cleanup old files
    # ------------------------------------------------------------------
    def cleanup_old_documents(self):
        """Delete documents older than STORAGE_RETENTION_DAYS.

        In production, queries the documents table and removes from Supabase
        Storage. In dev mode, removes old local files.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.STORAGE_RETENTION_DAYS)).isoformat()
        logger.info(f"Storage cleanup: removing documents older than {cutoff[:10]}")

        try:
            db, is_mock = _get_db()
        except Exception as e:
            logger.error(f"Storage cleanup: DB unavailable: {e}")
            return

        # Fetch old documents with a storage_key
        if is_mock:
            docs = db._read_file(db.documents_file)
            old_docs = [
                d for d in docs
                if d.get("storage_key") and d.get("created_at", "") < cutoff
            ]
        else:
            try:
                resp = (
                    db.table("documents")
                    .select("id,storage_key")
                    .lt("created_at", cutoff)
                    .not_.is_("storage_key", "null")
                    .execute()
                )
                old_docs = resp.data or []
            except Exception as e:
                logger.error(f"Storage cleanup: query failed: {e}")
                return

        deleted = 0
        for doc in old_docs:
            key = doc.get("storage_key")
            if not key:
                continue
            self.delete(key)
            # Mark as cleaned up in DB
            doc_id = doc.get("id")
            if doc_id:
                try:
                    if is_mock:
                        db.update_document_status(doc_id, "deleted")
                    else:
                        db.table("documents").update({"status": "deleted", "storage_key": None}).eq("id", doc_id).execute()
                except Exception:
                    pass
            deleted += 1

        if deleted:
            logger.info(f"Storage cleanup: removed {deleted} old document(s).")


def _get_db():
    if settings.ENVIRONMENT != "production":
        from app.utils.mock_db import MockDB
        return MockDB(), True
    else:
        from app.database import get_db_client
        client = get_db_client()
        if not client:
            raise RuntimeError("Database unavailable")
        return client, False


# Singleton
storage_service = StorageService()
