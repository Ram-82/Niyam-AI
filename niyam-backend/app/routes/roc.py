"""
ROC Routes — deadline tracking, penalty calculator, mark-as-filed.

GET  /api/roc/deadlines              → list ROC deadlines for authenticated user's business
POST /api/roc/deadlines/mark-filed   → mark a ROC deadline as completed
GET  /api/roc/penalty                → calculate ROC late filing penalty
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.config import settings
from app.utils.security import verify_token
from app.services.rules.deadline_rules import generate_deadlines_for_year, check_deadlines
from app.services.rules.penalty_rules import calculate_roc_penalty

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/roc", tags=["ROC"])
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


def _ensure_roc_deadlines(db, is_mock: bool, business_id: str) -> list:
    """
    Ensure ROC deadlines exist for the current year.
    Auto-seeds from statutory definitions if no deadlines are stored.
    """
    if is_mock:
        existing = db.get_deadlines_by_business(business_id, dl_type="roc")
    else:
        resp = db.table("deadlines").select("*").eq("business_id", business_id).eq("type", "roc").execute()
        existing = resp.data or []

    current_year = date.today().year
    year_prefix = str(current_year)

    has_current = any(
        dl.get("due_date", "").startswith(year_prefix)
        for dl in existing
    )

    if not has_current:
        all_deadlines = generate_deadlines_for_year(current_year)
        roc_deadlines = [dl for dl in all_deadlines if dl.get("type") == "roc"]
        now = datetime.now(timezone.utc).isoformat()

        for dl in roc_deadlines:
            dl["id"] = str(uuid.uuid4())
            dl["business_id"] = business_id
            dl["status"] = "upcoming"
            dl["filed_at"] = None
            dl["created_at"] = now

            if is_mock:
                db.upsert_deadline(dl)
            else:
                db.table("deadlines").insert(dl).execute()

        existing.extend(roc_deadlines)

    return [dl for dl in existing if dl.get("due_date", "").startswith(year_prefix)]


# ================================================================
# GET /api/roc/deadlines
# ================================================================
@router.get("/deadlines", response_model=dict)
async def get_roc_deadlines(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    List all ROC deadlines for the current year.
    Includes AOC-4 (financials), MGT-7 (annual return), DIR-3-KYC (director KYC).
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()
    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    deadlines = _ensure_roc_deadlines(db, is_mock, business_id)

    today = date.today()
    flags = check_deadlines(deadlines, today)

    for dl in deadlines:
        if dl.get("status") == "completed":
            continue
        try:
            due = date.fromisoformat(dl["due_date"])
            if due < today:
                dl["status"] = "overdue"
                dl["days_late"] = (today - due).days
                # Calculate running penalty
                penalty_rate = dl.get("penalty_rate") or 100.0
                dl["accrued_penalty"] = dl["days_late"] * penalty_rate
                # Disqualification risk
                dl["disqualification_risk"] = dl["days_late"] > 365
            elif (due - today).days <= 30:
                dl["status"] = "due_soon"
                dl["days_until"] = (due - today).days
            else:
                dl["status"] = "upcoming"
                dl["days_until"] = (due - today).days
        except (ValueError, KeyError):
            pass

    deadlines.sort(key=lambda d: d.get("due_date", "9999"))

    total = len(deadlines)
    completed = sum(1 for d in deadlines if d.get("status") == "completed")
    overdue = sum(1 for d in deadlines if d.get("status") == "overdue")
    any_disqualification = any(d.get("disqualification_risk") for d in deadlines)

    return {
        "success": True,
        "data": {
            "deadlines": deadlines,
            "summary": {
                "total": total,
                "completed": completed,
                "overdue": overdue,
                "upcoming": total - completed - overdue,
                "disqualification_risk": any_disqualification,
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
# POST /api/roc/deadlines/mark-filed
# ================================================================
class MarkFiledRequest(BaseModel):
    deadline_id: str
    srn_number: Optional[str] = None


@router.post("/deadlines/mark-filed", response_model=dict)
async def mark_roc_filed(
    body: MarkFiledRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Mark a ROC deadline as filed/completed."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()
    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for user")

    now = datetime.now(timezone.utc).isoformat()

    if is_mock:
        deadlines = db.get_deadlines_by_business(business_id, dl_type="roc")
        target = next((d for d in deadlines if d.get("id") == body.deadline_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Deadline not found")

        target["status"] = "completed"
        target["filed_at"] = now
        if body.srn_number:
            target["srn_number"] = body.srn_number
        db.upsert_deadline(target)
    else:
        check = (
            db.table("deadlines")
            .select("id")
            .eq("id", body.deadline_id)
            .eq("business_id", business_id)
            .eq("type", "roc")
            .single()
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Deadline not found")

        update = {"status": "completed", "filed_at": now}
        if body.srn_number:
            update["srn_number"] = body.srn_number
        db.table("deadlines").update(update).eq("id", body.deadline_id).execute()

    logger.info(f"ROC deadline marked filed id={body.deadline_id} user={user_id[:8]}")

    return {"success": True, "message": "Deadline marked as filed"}


# ================================================================
# GET /api/roc/penalty
# ================================================================
@router.get("/penalty", response_model=dict)
async def calculate_penalty(
    filing_type: str = Query(..., description="Filing type (AOC-4, MGT-7, DIR-3-KYC)"),
    due_date: str = Query(..., description="Due date (YYYY-MM-DD)"),
    as_of: Optional[str] = Query(None, description="Calculate as of date (default: today)"),
):
    """
    Calculate ROC late filing penalty.
    ₹100/day for AOC-4/MGT-7 (Companies Act 2013).
    No authentication required — public calculator.
    """
    valid_types = {"AOC-4", "MGT-7", "DIR-3-KYC"}
    if filing_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filing_type. Must be one of: {', '.join(sorted(valid_types))}",
        )

    try:
        calc_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid as_of date format. Use YYYY-MM-DD")

    result = calculate_roc_penalty(filing_type, due_date, today=calc_date)
    if result is None:
        return {
            "success": True,
            "data": {
                "penalty": 0,
                "days_late": 0,
                "disqualification_risk": False,
                "message": "Filing is not late as of the specified date",
            },
        }

    meta = result.metadata or {}
    return {
        "success": True,
        "data": {
            "penalty": result.impact_amount,
            "days_late": meta.get("days_late", 0),
            "rate_per_day": meta.get("rate_per_day", 100),
            "disqualification_risk": meta.get("disqualification_risk", False),
            "formula": meta.get("formula", ""),
            "message": result.message,
        },
    }
