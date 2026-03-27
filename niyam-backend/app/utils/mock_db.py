import json
import os
import threading
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class MockDB:
    """
    JSON-file-backed mock database for development.
    Thread-safe: all read/write operations are protected by a reentrant lock
    to prevent corruption from concurrent FastAPI requests.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._lock = threading.RLock()

        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        self.users_file = os.path.join(data_dir, "users.json")
        self.businesses_file = os.path.join(data_dir, "businesses.json")
        self.documents_file = os.path.join(data_dir, "documents.json")
        self.invoices_file = os.path.join(data_dir, "invoices.json")
        self.deadlines_file = os.path.join(data_dir, "deadlines.json")
        self.audit_log_file = os.path.join(data_dir, "audit_log.json")

        self._ensure_file(self.users_file)
        self._ensure_file(self.businesses_file)
        self._ensure_file(self.documents_file)
        self._ensure_file(self.invoices_file)
        self._ensure_file(self.deadlines_file)
        self._ensure_file(self.audit_log_file)

    def _ensure_file(self, filepath: str):
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump([], f)

    def _read_file(self, filepath: str) -> List[Dict]:
        with self._lock:
            try:
                with open(filepath, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
                return []

    def _write_file(self, filepath: str, data: List[Dict]):
        with self._lock:
            try:
                # Write to temp file first, then rename for atomicity
                tmp_path = filepath + ".tmp"
                with open(tmp_path, 'w') as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, filepath)
            except Exception as e:
                logger.error(f"Error writing {filepath}: {e}")

    def _read_modify_write(self, filepath: str, modifier):
        """Atomically read, modify, and write back a JSON file."""
        with self._lock:
            data = self._read_file(filepath)
            result = modifier(data)
            self._write_file(filepath, data)
            return result

    # User operations
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        users = self._read_file(self.users_file)
        for user in users:
            if user.get("email") == email:
                return user
        return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        users = self._read_file(self.users_file)
        for user in users:
            if user.get("id") == user_id:
                return user
        return None

    def create_user(self, user_data: Dict) -> Dict:
        def _append(users):
            users.append(user_data)
        self._read_modify_write(self.users_file, _append)
        return user_data

    def update_user_last_login(self, user_id: str, timestamp: str):
        def _update(users):
            for user in users:
                if user.get("id") == user_id:
                    user["last_login"] = timestamp
                    break
        self._read_modify_write(self.users_file, _update)

    # Business operations
    def create_business(self, business_data: Dict) -> Dict:
        def _append(businesses):
            businesses.append(business_data)
        self._read_modify_write(self.businesses_file, _append)
        return business_data

    def get_business_by_id(self, business_id: str) -> Optional[Dict]:
        businesses = self._read_file(self.businesses_file)
        for business in businesses:
            if business.get("id") == business_id:
                return business
        return None

    # Document operations
    def create_document(self, doc_data: Dict) -> Dict:
        def _append(docs):
            docs.append(doc_data)
        self._read_modify_write(self.documents_file, _append)
        return doc_data

    def get_document_by_id(self, doc_id: str) -> Optional[Dict]:
        docs = self._read_file(self.documents_file)
        for doc in docs:
            if doc.get("id") == doc_id:
                return doc
        return None

    def update_document_status(self, doc_id: str, status: str, processed_at: str = None):
        def _update(docs):
            for doc in docs:
                if doc.get("id") == doc_id:
                    doc["status"] = status
                    if processed_at:
                        doc["processed_at"] = processed_at
                    break
        self._read_modify_write(self.documents_file, _update)

    def update_document_raw_text(self, doc_id: str, raw_text: str):
        def _update(docs):
            for doc in docs:
                if doc.get("id") == doc_id:
                    doc["raw_text"] = raw_text
                    break
        self._read_modify_write(self.documents_file, _update)

    # Invoice operations
    def create_invoice(self, invoice_data: Dict) -> Dict:
        def _append(invoices):
            invoices.append(invoice_data)
        self._read_modify_write(self.invoices_file, _append)
        return invoice_data

    def get_invoices_by_business(self, business_id: str) -> List[Dict]:
        invoices = self._read_file(self.invoices_file)
        return [inv for inv in invoices if inv.get("business_id") == business_id]

    # Deadline operations
    def get_deadlines_by_business(self, business_id: str, dl_type: str = None) -> List[Dict]:
        deadlines = self._read_file(self.deadlines_file)
        results = [dl for dl in deadlines if dl.get("business_id") == business_id]
        if dl_type:
            results = [dl for dl in results if dl.get("type") == dl_type]
        return results

    def upsert_deadline(self, deadline_data: Dict) -> Dict:
        """Insert or update a deadline by id."""
        dl_id = deadline_data.get("id")
        def _upsert(deadlines):
            for i, dl in enumerate(deadlines):
                if dl.get("id") == dl_id:
                    deadlines[i] = deadline_data
                    return
            deadlines.append(deadline_data)
        self._read_modify_write(self.deadlines_file, _upsert)
        return deadline_data

    def update_deadline_status(self, dl_id: str, new_status: str, filed_at: str = None):
        def _update(deadlines):
            for dl in deadlines:
                if dl.get("id") == dl_id:
                    dl["status"] = new_status
                    if filed_at:
                        dl["filed_at"] = filed_at
                    break
        self._read_modify_write(self.deadlines_file, _update)

    # Audit log operations
    def append_audit_log(self, entry: Dict) -> Dict:
        def _append(logs):
            logs.append(entry)
            # Keep only last 1000 entries per file to prevent bloat
            if len(logs) > 1000:
                del logs[:len(logs) - 1000]
        self._read_modify_write(self.audit_log_file, _append)
        return entry

    def get_audit_logs(self, business_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        logs = self._read_file(self.audit_log_file)
        filtered = [l for l in logs if l.get("business_id") == business_id]
        # Most recent first
        filtered.sort(key=lambda l: l.get("timestamp", ""), reverse=True)
        return filtered[offset:offset + limit]
