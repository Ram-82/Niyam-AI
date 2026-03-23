"""
Deadline Rules — statutory deadline generation and overdue detection.

Generates all Indian compliance deadlines for a business and flags
approaching/overdue ones with severity and impact.
"""

from datetime import date, timedelta
from typing import List

from app.services.rules.base import ComplianceFlag, Severity, FlagCategory

# ============================================================
# Statutory Deadline Definitions
# ============================================================
# Each entry: (subtype, description, day_of_month, months, filing_portal)
# months: list of months when this deadline applies (1-12)

GST_DEADLINES = [
    ("GSTR-1", "Monthly sales return", 11, list(range(1, 13)), "https://gst.gov.in"),
    ("GSTR-3B", "Monthly summary return + payment", 20, list(range(1, 13)), "https://gst.gov.in"),
    ("GSTR-9", "Annual return", 31, [12], "https://gst.gov.in"),  # Due Dec 31 for prev FY
]

TDS_DEADLINES = [
    ("TDS-Payment", "Monthly TDS deposit", 7, list(range(1, 13)), "https://incometax.gov.in"),
    ("24Q", "Quarterly TDS return (salary)", 31, [7, 10, 1, 5], "https://incometax.gov.in"),
    ("26Q", "Quarterly TDS return (non-salary)", 31, [7, 10, 1, 5], "https://incometax.gov.in"),
]

ROC_DEADLINES = [
    ("AOC-4", "Financial statements filing", 30, [10], "https://mca.gov.in"),  # Oct 30
    ("MGT-7", "Annual return filing", 29, [11], "https://mca.gov.in"),  # Nov 29
    ("DIR-3-KYC", "Director KYC", 30, [9], "https://mca.gov.in"),  # Sep 30
]

# Days thresholds for severity
CRITICAL_DAYS = 0       # overdue
ERROR_DAYS = 3          # due within 3 days
WARNING_DAYS = 7        # due within 7 days
INFO_DAYS = 30          # due within 30 days


def generate_deadlines_for_year(year: int) -> List[dict]:
    """
    Generate all statutory deadlines for a given calendar year.
    Returns list of deadline dicts (ready for DB insertion).
    """
    deadlines = []

    for subtype, desc, day, months, portal in GST_DEADLINES:
        for month in months:
            try:
                due = date(year, month, min(day, 28))
            except ValueError:
                due = date(year, month, 28)
            deadlines.append({
                "type": "gst",
                "subtype": subtype,
                "due_date": due.isoformat(),
                "description": desc,
                "filing_portal": portal,
                "penalty_rate": 50.0,  # ₹50/day for GST late filing
            })

    for subtype, desc, day, months, portal in TDS_DEADLINES:
        for month in months:
            try:
                due = date(year, month, min(day, 28))
            except ValueError:
                due = date(year, month, 28)
            deadlines.append({
                "type": "tds",
                "subtype": subtype,
                "due_date": due.isoformat(),
                "description": desc,
                "filing_portal": portal,
                "penalty_rate": None,  # TDS uses interest-based penalty
            })

    for subtype, desc, day, months, portal in ROC_DEADLINES:
        for month in months:
            try:
                due = date(year, month, min(day, 28))
            except ValueError:
                due = date(year, month, 28)
            deadlines.append({
                "type": "roc",
                "subtype": subtype,
                "due_date": due.isoformat(),
                "description": desc,
                "filing_portal": portal,
                "penalty_rate": 200.0,  # ₹200/day for ROC
            })

    return deadlines


def check_deadlines(deadlines: List[dict], today: date = None) -> List[ComplianceFlag]:
    """
    Check a list of deadlines against today's date.
    Returns ComplianceFlag for each approaching or overdue deadline.

    Only flags non-completed deadlines.
    """
    if today is None:
        today = date.today()

    flags = []

    for dl in deadlines:
        status = dl.get("status", "upcoming")
        if status == "completed":
            continue

        due_str = dl.get("due_date", "")
        try:
            due = date.fromisoformat(due_str)
        except (ValueError, TypeError):
            continue

        days_until = (due - today).days
        subtype = dl.get("subtype", "unknown")
        dl_type = dl.get("type", "gst")
        category = dl_type
        penalty_rate = dl.get("penalty_rate") or 0

        if days_until < CRITICAL_DAYS:
            # Overdue
            days_late = abs(days_until)
            impact = days_late * penalty_rate if penalty_rate else 0

            flags.append(ComplianceFlag(
                rule_id=f"{dl_type}_overdue",
                category=category,
                severity=Severity.CRITICAL,
                message=f"{subtype} is {days_late} days overdue",
                impact_amount=impact,
                due_date=due_str,
                related_id=dl.get("id"),
                metadata={
                    "subtype": subtype,
                    "days_late": days_late,
                    "penalty_rate_per_day": penalty_rate,
                },
            ))

        elif days_until <= ERROR_DAYS:
            flags.append(ComplianceFlag(
                rule_id=f"{dl_type}_due_imminent",
                category=category,
                severity=Severity.ERROR,
                message=f"{subtype} due in {days_until} day{'s' if days_until != 1 else ''}",
                impact_amount=penalty_rate,  # 1 day late penalty
                due_date=due_str,
                related_id=dl.get("id"),
                metadata={"subtype": subtype, "days_until": days_until},
            ))

        elif days_until <= WARNING_DAYS:
            flags.append(ComplianceFlag(
                rule_id=f"{dl_type}_deadline_approaching",
                category=category,
                severity=Severity.WARNING,
                message=f"{subtype} due in {days_until} days",
                due_date=due_str,
                related_id=dl.get("id"),
                metadata={"subtype": subtype, "days_until": days_until},
            ))

        elif days_until <= INFO_DAYS:
            flags.append(ComplianceFlag(
                rule_id=f"{dl_type}_deadline_upcoming",
                category=category,
                severity=Severity.INFO,
                message=f"{subtype} due in {days_until} days",
                due_date=due_str,
                related_id=dl.get("id"),
                metadata={"subtype": subtype, "days_until": days_until},
            ))

    # Sort: critical first, then error, warning, info
    severity_order = {
        Severity.CRITICAL: 0, Severity.ERROR: 1,
        Severity.WARNING: 2, Severity.INFO: 3,
    }
    flags.sort(key=lambda f: severity_order.get(f.severity, 99))

    return flags
