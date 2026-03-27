"""
Penalty Rules — calculate financial impact of non-compliance.

Implements actual Indian penalty formulas:
- GST: ₹50/day (₹25 CGST + ₹25 SGST), max ₹5,000
- TDS: 1.5% per month interest + ₹200/day for return
- ROC: ₹100/day (AOC-4/MGT-7), plus director disqualification risk
"""

from datetime import date
from typing import Optional

from app.services.rules.base import ComplianceFlag, Severity


def calculate_gst_penalty(
    filing_type: str,
    due_date: str,
    today: date = None,
    is_nil_return: bool = False,
) -> ComplianceFlag:
    """
    Calculate GST late filing penalty.

    GSTR-3B/GSTR-1: ₹50/day (₹25 CGST + ₹25 SGST) up to ₹5,000
    Nil return: ₹20/day (₹10 CGST + ₹10 SGST) up to ₹500
    """
    if today is None:
        today = date.today()

    try:
        due = date.fromisoformat(due_date)
    except (ValueError, TypeError):
        return None

    if today <= due:
        return None  # not late yet

    days_late = (today - due).days

    if is_nil_return:
        rate_per_day = 20.0   # ₹10 CGST + ₹10 SGST for nil returns
        max_penalty = 500.0
    else:
        rate_per_day = 50.0   # ₹25 CGST + ₹25 SGST for regular returns
        max_penalty = 5000.0

    penalty = min(days_late * rate_per_day, max_penalty)

    return_type = "nil return" if is_nil_return else filing_type

    return ComplianceFlag(
        rule_id="gst_late_penalty",
        category="gst",
        severity=Severity.CRITICAL if days_late > 15 else Severity.ERROR,
        message=f"{return_type} is {days_late} days late — penalty ₹{penalty:,.0f}",
        action_required=f"File {filing_type} immediately to avoid further penalty accrual",
        impact_amount=penalty,
        due_date=due_date,
        metadata={
            "filing_type": filing_type,
            "is_nil_return": is_nil_return,
            "days_late": days_late,
            "rate_per_day": rate_per_day,
            "max_penalty": max_penalty,
            "formula": f"min({days_late} × ₹{rate_per_day}, ₹{max_penalty})",
        },
    )


def calculate_tds_interest(
    amount: float,
    due_date: str,
    today: date = None,
    deduction_date: Optional[str] = None,
) -> ComplianceFlag:
    """
    Calculate TDS late payment interest.

    Section 201(1A):
    - Late deduction: 1% per month from date payable to date of deduction
    - Late deposit: 1.5% per month from date of deduction to date of deposit

    We calculate the late deposit case (more common).
    """
    if today is None:
        today = date.today()

    try:
        due = date.fromisoformat(due_date)
    except (ValueError, TypeError):
        return None

    if today <= due:
        return None

    days_late = (today - due).days
    months_late = max(1, (days_late + 29) // 30)  # round up to nearest month
    rate = 0.015  # 1.5% per month

    interest = round(amount * rate * months_late, 2)

    return ComplianceFlag(
        rule_id="tds_late_interest",
        category="tds",
        severity=Severity.CRITICAL if months_late >= 3 else Severity.ERROR,
        message=f"TDS payment {months_late} month{'s' if months_late > 1 else ''} late — interest ₹{interest:,.0f}",
        action_required="Deposit TDS amount with interest via challan on incometax.gov.in",
        impact_amount=interest,
        due_date=due_date,
        metadata={
            "principal": amount,
            "months_late": months_late,
            "rate_per_month": rate,
            "formula": f"₹{amount:,.0f} × {rate*100}% × {months_late} months",
        },
    )


def calculate_roc_penalty(
    filing_type: str,
    due_date: str,
    today: date = None,
) -> ComplianceFlag:
    """
    Calculate ROC late filing penalty.

    AOC-4 / MGT-7: ₹100/day, no cap (Companies Act 2013)
    Continued default (>3 years): director disqualification risk
    """
    if today is None:
        today = date.today()

    try:
        due = date.fromisoformat(due_date)
    except (ValueError, TypeError):
        return None

    if today <= due:
        return None

    days_late = (today - due).days
    rate_per_day = 100.0  # ₹100/day for ROC filings

    penalty = days_late * rate_per_day

    severity = Severity.ERROR
    message = f"{filing_type} is {days_late} days late — penalty ₹{penalty:,.0f}"

    # Escalation: >365 days = director disqualification risk
    if days_late > 365:
        severity = Severity.CRITICAL
        message += " — DIRECTOR DISQUALIFICATION RISK"

    action = f"File {filing_type} on MCA portal immediately — penalty ₹{rate_per_day:.0f}/day accruing"
    if days_late > 365:
        action = f"URGENT: File {filing_type} on MCA portal — director disqualification proceedings may begin"

    return ComplianceFlag(
        rule_id="roc_late_penalty",
        category="roc",
        severity=severity,
        message=message,
        action_required=action,
        impact_amount=penalty,
        due_date=due_date,
        metadata={
            "filing_type": filing_type,
            "days_late": days_late,
            "rate_per_day": rate_per_day,
            "disqualification_risk": days_late > 365,
            "formula": f"{days_late} × ₹{rate_per_day}",
        },
    )
