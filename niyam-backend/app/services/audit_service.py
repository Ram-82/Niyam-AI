"""
Audit Service — records all compliance-relevant user actions.

Usage:
    from app.services.audit_service import audit_log
    audit_log(business_id, user_id, "invoice_uploaded", details={"filename": "inv.pdf"})
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def audit_log(
    business_id: str,
    user_id: str,
    action: str,
    details: Optional[dict] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> None:
    """
    Record an audit log entry.

    Args:
        business_id: The business this action belongs to
        user_id: Who performed the action
        action: Action type (e.g. "invoice_uploaded", "invoice_corrected", "deadline_filed")
        details: Extra context about the action
        resource_type: Type of resource acted on (e.g. "invoice", "deadline")
        resource_id: ID of the resource acted on
    """
    entry = {
        "id": str(uuid.uuid4()),
        "business_id": business_id,
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        if settings.ENVIRONMENT == "production":
            from app.database import get_db_client
            db = get_db_client()
            if db:
                db.table("audit_logs").insert(entry).execute()
        else:
            from app.utils.mock_db import MockDB
            MockDB().append_audit_log(entry)
    except Exception as e:
        # Audit logging should never break the main flow
        logger.warning(f"Audit log failed (non-fatal): {e}")
