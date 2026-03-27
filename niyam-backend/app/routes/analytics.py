"""
Analytics Routes — aggregate invoice and compliance data for charts.

GET  /api/analytics/trends         → monthly tax/ITC/cashflow trends
GET  /api/analytics/invoice-stats  → invoice processing summary
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
security = HTTPBearer()


def _get_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    payload = verify_token(credentials.credentials)
    return payload.get("sub")


def _get_db():
    if settings.ENVIRONMENT == "production":
        from app.database import get_db_client
        client = get_db_client()
        if not client:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return client, False
    else:
        from app.utils.mock_db import MockDB
        return MockDB(), True


def _get_business_id(db, is_mock: bool, user_id: str) -> Optional[str]:
    try:
        if is_mock:
            user = db.get_user_by_id(user_id)
            return user["business_id"] if user else None
        else:
            resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
            return resp.data.get("business_id") if resp.data else None
    except Exception:
        return None


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_invoice_month(invoice: dict) -> Optional[str]:
    """Extract YYYY-MM from an invoice's date or created_at."""
    for field in ("invoice_date", "created_at"):
        raw = invoice.get(field)
        if not raw:
            continue
        try:
            s = str(raw)[:10]  # "2026-03-15" or "2026-03-15T..."
            if len(s) >= 7 and s[4] == '-':
                return s[:7]  # "2026-03"
        except Exception:
            continue
    return None


def _aggregate_monthly(invoices: list, months: int = 6) -> dict:
    """
    Aggregate invoice financials by month.

    Returns:
        {
            "labels": ["Oct", "Nov", ...],
            "taxLiability": [1234, ...],
            "cashFlow": [5678, ...],     # total_amount
            "itcAvailable": [900, ...],  # cgst+sgst+igst
        }
    """
    today = date.today()

    # Build ordered list of month keys
    month_keys = []
    for offset in range(months - 1, -1, -1):
        m = today.month - offset
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        month_keys.append(f"{y}-{m:02d}")

    # Aggregate
    totals_by_month = defaultdict(lambda: {"total": 0.0, "tax": 0.0, "itc": 0.0, "count": 0})

    for inv in invoices:
        mk = _parse_invoice_month(inv)
        if not mk or mk not in month_keys:
            continue

        bucket = totals_by_month[mk]
        bucket["total"] += float(inv.get("total_amount") or 0)
        cgst = float(inv.get("cgst") or 0)
        sgst = float(inv.get("sgst") or 0)
        igst = float(inv.get("igst") or 0)
        bucket["tax"] += cgst + sgst + igst
        bucket["itc"] += cgst + sgst + igst  # ITC = input tax on purchase invoices
        bucket["count"] += 1

    labels = []
    tax_liability = []
    cash_flow = []
    itc_available = []

    for mk in month_keys:
        m_int = int(mk.split("-")[1])
        labels.append(MONTH_NAMES[m_int - 1])
        bucket = totals_by_month[mk]
        tax_liability.append(round(bucket["tax"], 2))
        cash_flow.append(round(bucket["total"], 2))
        itc_available.append(round(bucket["itc"], 2))

    return {
        "labels": labels,
        "taxLiability": tax_liability,
        "cashFlow": cash_flow,
        "itcAvailable": itc_available,
    }


# ================================================================
# GET /api/analytics/trends
# ================================================================
@router.get("/trends", response_model=dict)
async def get_trends(
    months: int = Query(default=6, ge=3, le=12, description="Number of months to include"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Monthly financial trends aggregated from stored invoices.

    Returns chart-ready data with labels, taxLiability, cashFlow, itcAvailable arrays.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = resp.data or []

    data_6m = _aggregate_monthly(invoices, months=6)
    data_1y = _aggregate_monthly(invoices, months=12)
    data_qtd = _aggregate_monthly(invoices, months=3)

    return {
        "success": True,
        "data": {
            "6M": data_6m,
            "1Y": data_1y,
            "QTD": data_qtd,
        },
    }


# ================================================================
# GET /api/analytics/invoice-stats
# ================================================================
@router.get("/invoice-stats", response_model=dict)
async def get_invoice_stats(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Summary statistics for processed invoices.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = resp.data or []

    total_invoices = len(invoices)
    needs_review = sum(1 for inv in invoices if inv.get("needs_review"))
    total_amount = sum(float(inv.get("total_amount") or 0) for inv in invoices)
    total_tax = sum(
        float(inv.get("cgst") or 0) + float(inv.get("sgst") or 0) + float(inv.get("igst") or 0)
        for inv in invoices
    )
    avg_confidence = (
        sum(float(inv.get("confidence") or 0) for inv in invoices) / total_invoices
        if total_invoices > 0 else 0.0
    )

    return {
        "success": True,
        "data": {
            "total_invoices": total_invoices,
            "needs_review": needs_review,
            "reviewed": total_invoices - needs_review,
            "total_amount": round(total_amount, 2),
            "total_tax": round(total_tax, 2),
            "avg_confidence": round(avg_confidence, 2),
        },
    }
