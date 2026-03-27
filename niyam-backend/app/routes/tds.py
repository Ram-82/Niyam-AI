"""
TDS Routes — deadline tracking, interest calculator, mark-as-filed.

GET  /api/tds/deadlines              → list TDS deadlines for authenticated user's business
POST /api/tds/deadlines/mark-filed   → mark a TDS deadline as completed
GET  /api/tds/interest               → calculate TDS late payment interest
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.security import verify_token
from app.services.rules.deadline_rules import generate_deadlines_for_year, check_deadlines
from app.services.rules.penalty_rules import calculate_tds_interest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tds", tags=["TDS"])
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


def _ensure_tds_deadlines(db, is_mock: bool, business_id: str) -> list:
    """
    Ensure TDS deadlines exist for the current year.
    Auto-seeds from statutory definitions if no deadlines are stored.
    """
    if is_mock:
        existing = db.get_deadlines_by_business(business_id, dl_type="tds")
    else:
        resp = db.table("deadlines").select("*").eq("business_id", business_id).eq("type", "tds").execute()
        existing = resp.data or []

    current_year = date.today().year
    year_prefix = str(current_year)

    # Check if current year deadlines exist
    has_current = any(
        dl.get("due_date", "").startswith(year_prefix)
        for dl in existing
    )

    if not has_current:
        all_deadlines = generate_deadlines_for_year(current_year)
        tds_deadlines = [dl for dl in all_deadlines if dl.get("type") == "tds"]
        now = datetime.now(timezone.utc).isoformat()

        for dl in tds_deadlines:
            dl["id"] = str(uuid.uuid4())
            dl["business_id"] = business_id
            dl["status"] = "upcoming"
            dl["filed_at"] = None
            dl["created_at"] = now

            if is_mock:
                db.upsert_deadline(dl)
            else:
                db.table("deadlines").insert(dl).execute()

        existing.extend(tds_deadlines)

    return [dl for dl in existing if dl.get("due_date", "").startswith(year_prefix)]


# ================================================================
# GET /api/tds/deadlines
# ================================================================
@router.get("/deadlines", response_model=dict)
async def get_tds_deadlines(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    List all TDS deadlines for the current year.
    Each deadline includes status (upcoming/completed/overdue) and flags.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()
    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    deadlines = _ensure_tds_deadlines(db, is_mock, business_id)

    # Compute flags for overdue/approaching deadlines
    today = date.today()
    flags = check_deadlines(deadlines, today)

    # Enrich deadlines with computed status
    for dl in deadlines:
        if dl.get("status") == "completed":
            continue
        try:
            due = date.fromisoformat(dl["due_date"])
            if due < today:
                dl["status"] = "overdue"
                dl["days_late"] = (today - due).days
            elif (due - today).days <= 7:
                dl["status"] = "due_soon"
                dl["days_until"] = (due - today).days
            else:
                dl["status"] = "upcoming"
                dl["days_until"] = (due - today).days
        except (ValueError, KeyError):
            pass

    # Sort by due_date
    deadlines.sort(key=lambda d: d.get("due_date", "9999"))

    # Summary stats
    total = len(deadlines)
    completed = sum(1 for d in deadlines if d.get("status") == "completed")
    overdue = sum(1 for d in deadlines if d.get("status") == "overdue")

    return {
        "success": True,
        "data": {
            "deadlines": deadlines,
            "summary": {
                "total": total,
                "completed": completed,
                "overdue": overdue,
                "upcoming": total - completed - overdue,
            },
            "flags": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                    "message": f.message,
                    "action_required": f.action_required,
                    "due_date": f.due_date,
                    "impact_amount": f.impact_amount,
                }
                for f in flags
            ],
        },
    }


# ================================================================
# POST /api/tds/deadlines/mark-filed
# ================================================================
class MarkFiledRequest(BaseModel):
    deadline_id: str
    challan_number: Optional[str] = None
    amount_paid: Optional[float] = None


@router.post("/deadlines/mark-filed", response_model=dict)
async def mark_tds_filed(
    body: MarkFiledRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Mark a TDS deadline as filed/completed."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()
    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    now = datetime.now(timezone.utc).isoformat()

    if is_mock:
        deadlines = db.get_deadlines_by_business(business_id, dl_type="tds")
        target = next((d for d in deadlines if d.get("id") == body.deadline_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Deadline not found")

        target["status"] = "completed"
        target["filed_at"] = now
        if body.challan_number:
            target["challan_number"] = body.challan_number
        if body.amount_paid is not None:
            target["amount_paid"] = body.amount_paid
        db.upsert_deadline(target)
    else:
        check = (
            db.table("deadlines")
            .select("id")
            .eq("id", body.deadline_id)
            .eq("business_id", business_id)
            .eq("type", "tds")
            .single()
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Deadline not found")

        update = {"status": "completed", "filed_at": now}
        if body.challan_number:
            update["challan_number"] = body.challan_number
        if body.amount_paid is not None:
            update["amount_paid"] = body.amount_paid
        db.table("deadlines").update(update).eq("id", body.deadline_id).execute()

    logger.info(f"TDS deadline marked filed id={body.deadline_id} user={user_id[:8]}")

    return {"success": True, "message": "Deadline marked as filed"}


# ================================================================
# GET /api/tds/interest
# ================================================================
@router.get("/interest", response_model=dict)
async def calculate_interest(
    amount: float = Query(..., gt=0, description="TDS amount (₹)"),
    due_date: str = Query(..., description="Due date (YYYY-MM-DD)"),
    as_of: Optional[str] = Query(None, description="Calculate as of date (default: today)"),
):
    """
    Calculate TDS late payment interest (Section 201(1A)).
    1.5% per month from due date to current/specified date.
    No authentication required — public calculator.
    """
    try:
        calc_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid as_of date format. Use YYYY-MM-DD")

    result = calculate_tds_interest(amount, due_date, today=calc_date)
    if result is None:
        return {
            "success": True,
            "data": {
                "interest": 0,
                "months_late": 0,
                "message": "Payment is not late as of the specified date",
            },
        }

    meta = result.metadata or {}
    return {
        "success": True,
        "data": {
            "interest": result.impact_amount,
            "months_late": meta.get("months_late", 0),
            "principal": amount,
            "rate_per_month": "1.5%",
            "formula": meta.get("formula", ""),
            "message": result.message,
        },
    }
