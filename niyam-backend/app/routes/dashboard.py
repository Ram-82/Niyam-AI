"""
Dashboard Routes — actionable intelligence for the user.

GET  /api/dashboard/summary    → Full dashboard (top actions + financials + compliance + timeline)
POST /api/dashboard/refresh    → Force re-compute with fresh ITC/compliance data
"""

import logging
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token
from app.services.dashboard_service import DashboardService
from app.services.rules import RulesEngine
from app.services.rules.deadline_rules import generate_deadlines_for_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
security = HTTPBearer()

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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


def _get_business_id(db, is_mock: bool, user_id: str) -> str:
    if is_mock:
        user = db.get_user_by_id(user_id)
        return user["business_id"] if user else None
    else:
        resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        return resp.data.get("business_id") if resp.data else None


@router.get("/summary", response_model=dict)
async def get_dashboard_summary(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    top_n: int = Query(default=3, ge=1, le=10, description="Number of top actions"),
):
    """
    Get the full dashboard: top actions, financials, compliance, timeline.

    The user opens this and instantly knows:
    "What are the top 3 things I must fix today to save money?"
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    # ---- Fetch data ----
    # Deadlines
    if is_mock:
        deadlines = generate_deadlines_for_year(date.today().year)
    else:
        dl_resp = db.table("compliance_deadlines").select("*").eq("business_id", business_id).execute()
        deadlines = dl_resp.data or []
        if not deadlines:
            deadlines = generate_deadlines_for_year(date.today().year)

    # Invoices
    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        inv_resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = inv_resp.data or []

    # ---- Run Rules Engine ----
    engine = RulesEngine()
    compliance_report = engine.run_all(deadlines=deadlines, invoices=invoices)
    compliance_flags = compliance_report.get("flags", [])

    # ---- Fetch latest ITC results (if available) ----
    itc_results = []
    itc_financials = None
    if not is_mock:
        itc_resp = (
            db.table("itc_matches")
            .select("*")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        itc_results = itc_resp.data or []

    # ---- Build Dashboard ----
    dashboard = DashboardService()
    result = dashboard.build(
        compliance_flags=compliance_flags,
        compliance_report=compliance_report,
        itc_results=itc_results,
        itc_financials=itc_financials,
        top_n=top_n,
    )

    # ---- Health History (for trend chart) ----
    # Compute a per-month compliance health proxy from invoices:
    # score = 100 - (flagged_invoices / total) * 50 - penalty_weight
    today = date.today()
    month_keys = []
    for offset in range(5, -1, -1):
        m = today.month - offset
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        month_keys.append(f"{y}-{m:02d}")

    inv_by_month = defaultdict(lambda: {"total": 0, "flagged": 0})
    for inv in invoices:
        inv_date = inv.get("invoice_date") or inv.get("created_at") or ""
        mk = str(inv_date)[:7]
        if mk in month_keys:
            inv_by_month[mk]["total"] += 1
            if inv.get("needs_review"):
                inv_by_month[mk]["flagged"] += 1

    labels = []
    health_history = []
    for mk in month_keys:
        m_int = int(mk.split("-")[1])
        labels.append(MONTH_NAMES[m_int - 1])
        bucket = inv_by_month[mk]
        if bucket["total"] > 0:
            flag_ratio = bucket["flagged"] / bucket["total"]
            score = max(60, round(100 - flag_ratio * 40))
        else:
            score = 100  # No invoices = no issues = healthy
        health_history.append(score)

    result["labels"] = labels
    result["health_history"] = health_history

    # ---- Invoice Stats ----
    result["invoice_stats"] = {
        "total_invoices": len(invoices),
        "needs_review": sum(1 for inv in invoices if inv.get("needs_review")),
        "total_amount": round(sum(float(inv.get("total_amount") or 0) for inv in invoices), 2),
    }

    return {
        "success": True,
        "data": result,
    }
