"""
Rules Engine — modular compliance intelligence.

Each rule module is independent and returns structured ComplianceFlag objects.
The engine orchestrates them and produces a compliance report.

Architecture:
    rules/
    ├── __init__.py          ← this file (engine orchestrator)
    ├── base.py              ← ComplianceFlag model + severity enum
    ├── deadline_rules.py    ← statutory deadline generation + overdue detection
    ├── invoice_rules.py     ← invoice-level validation (GSTIN, amounts, duplicates)
    └── penalty_rules.py     ← penalty calculation (GST, TDS, ROC late fees)
"""

from app.services.rules.base import ComplianceFlag, Severity
from app.services.rules.engine import RulesEngine

__all__ = ["RulesEngine", "ComplianceFlag", "Severity"]
