"""
Base types for the Rules Engine.

Every rule produces ComplianceFlag objects — structured, typed,
ready for DB storage and dashboard display.
"""

from enum import Enum
from typing import Optional


class Severity(str, Enum):
    """Flag severity levels, ordered by urgency."""
    INFO = "info"           # FYI — no action needed
    WARNING = "warning"     # Action needed soon
    ERROR = "error"         # Immediate action required
    CRITICAL = "critical"   # Overdue / penalty accruing


class FlagCategory(str, Enum):
    """Top-level compliance categories."""
    GST = "gst"
    TDS = "tds"
    ROC = "roc"
    INVOICE = "invoice"
    ITC = "itc"


class ComplianceFlag:
    """
    A single compliance issue detected by the Rules Engine.

    Designed for:
    - DB storage (compliance_flags table)
    - Dashboard rendering (category + severity → color/icon)
    - Rules Engine chaining (downstream rules can read upstream flags)
    """

    __slots__ = (
        "rule_id",          # unique rule identifier (e.g. "gst_deadline_approaching")
        "category",         # FlagCategory enum value
        "severity",         # Severity enum value
        "message",          # human-readable description
        "action_required",  # what the user should do RIGHT NOW
        "impact_amount",    # estimated financial impact in ₹ (penalty, lost ITC, etc.)
        "due_date",         # relevant deadline (ISO string or None)
        "related_id",       # FK to invoice_id, deadline_id, etc.
        "metadata",         # extra context (dict) for dashboard
    )

    def __init__(
        self,
        rule_id: str,
        category: str,
        severity: str,
        message: str,
        action_required: Optional[str] = None,
        impact_amount: float = 0.0,
        due_date: Optional[str] = None,
        related_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.rule_id = rule_id
        self.category = category
        self.severity = severity
        self.message = message
        self.action_required = action_required
        self.impact_amount = impact_amount
        self.due_date = due_date
        self.related_id = related_id
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "action_required": self.action_required,
            "impact_amount": self.impact_amount,
            "due_date": self.due_date,
            "related_id": self.related_id,
            "metadata": self.metadata,
        }

    def __repr__(self):
        return f"<Flag [{self.severity}] {self.rule_id}: {self.message}>"
