"""
ITC Matching Routes — reconcile purchase invoices against GSTR-2B.

POST /api/itc-match          → Run ITC reconciliation
POST /api/itc-match/upload2b → Upload GSTR-2B JSON for matching
GET  /api/itc-match/results  → Get latest ITC match results
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.security import verify_token
from app.services.itc_service import ITCService, parse_gstr2b
from app.services.itc_matcher import MatchConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/itc-match", tags=["ITC Matching"])
security = HTTPBearer()


# ============================================================
# Request / Response Models
# ============================================================

class ITCMatchRequest(BaseModel):
    """Request body for ITC reconciliation."""
    gstr2b_data: dict = Field(..., description="GSTR-2B JSON data (official or flat format)")
    period: Optional[str] = Field(None, description="Filing period label (e.g. 'Mar 2026')")
    amount_tolerance: float = Field(1.0, ge=0, le=100, description="Amount tolerance in ₹")
    gst_tolerance: float = Field(1.0, ge=0, le=100, description="GST amount tolerance in ₹")
    fuzzy_invoice_number: bool = Field(True, description="Enable fuzzy invoice number matching")


class GSTR2BUploadRequest(BaseModel):
    """Upload GSTR-2B data for storage."""
    gstr2b_data: dict = Field(..., description="GSTR-2B JSON data")
    period: Optional[str] = Field(None, description="Filing period")


# ============================================================
# Helpers
# ============================================================

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


# ============================================================
# POST /api/itc-match — Run ITC Reconciliation
# ============================================================

@router.post("", response_model=dict)
async def run_itc_match(
    request: ITCMatchRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Run ITC reconciliation: match purchase invoices against GSTR-2B data.

    Accepts GSTR-2B JSON in either:
    1. Official GST portal format (nested under data.docdata.b2b)
    2. Simplified flat format (list of invoices)

    Returns:
    - match_results: per-invoice match details with actions
    - financials: ITC summary (available, claimed, at-risk, recoverable)
    - vendor_scores: per-vendor reliability scores
    - action_summary: grouped by priority (critical/high/medium/low)
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    # Fetch invoices from DB
    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        inv_resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = inv_resp.data or []

    if not invoices:
        return {
            "success": True,
            "data": {
                "match_results": [],
                "financials": {
                    "total_itc_available": 0,
                    "total_itc_claimed": 0,
                    "total_itc_at_risk": 0,
                    "recoverable_itc": 0,
                    "net_itc_position": 0,
                    "utilization_rate": 0,
                },
                "match_breakdown": {},
                "vendor_scores": [],
                "action_summary": {"critical": [], "high": [], "medium": [], "low": []},
                "metadata": {"total_invoices": 0, "total_2b_entries": 0, "total_matches": 0},
            },
            "message": "No invoices found to match. Upload and extract invoices first.",
        }

    # Configure matcher
    config = MatchConfig(
        amount_tolerance=request.amount_tolerance,
        gst_tolerance=request.gst_tolerance,
        fuzzy_invoice_number=request.fuzzy_invoice_number,
    )

    # Run reconciliation
    service = ITCService(config)
    try:
        report = service.reconcile(
            invoices=invoices,
            gstr2b_json=request.gstr2b_data,
            period=request.period,
        )
    except Exception as e:
        logger.error(f"ITC reconciliation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"ITC reconciliation failed: {str(e)}",
        )

    # Save results to DB (if not mock)
    now = datetime.now(timezone.utc).isoformat()
    if not is_mock:
        try:
            # Save each match result
            for result in report.get("match_results", []):
                match_record = {
                    "business_id": business_id,
                    "invoice_id": result.get("invoice_id"),
                    "gstr2b_id": result.get("gstr2b_id"),
                    "match_type": str(result.get("match_type", "")),
                    "severity": str(result.get("severity", "")),
                    "vendor_gstin": result.get("vendor_gstin"),
                    "invoice_number": result.get("invoice_number"),
                    "eligible_itc": float(result.get("eligible_itc") or 0),
                    "claimed_itc": float(result.get("claimed_itc") or 0),
                    "itc_at_risk": float(result.get("itc_at_risk") or 0),
                    "action_required": result.get("action_required"),
                    "reason": result.get("reason"),
                    "confidence_score": result.get("confidence_score"),
                    "created_at": now,
                }
                db.table("itc_matches").insert(match_record).execute()
        except Exception as e:
            logger.warning(f"Failed to save ITC results to DB: {e}")
            # Non-fatal: still return results

    logger.info(
        f"ITC match complete business={business_id} "
        f"invoices={len(invoices)} matches={len(report.get('match_results', []))}"
    )

    return {
        "success": True,
        "data": report,
    }


# ============================================================
# POST /api/itc-match/upload2b — Upload GSTR-2B Data
# ============================================================

@router.post("/upload2b", response_model=dict)
async def upload_gstr2b(
    request: GSTR2BUploadRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Upload and parse GSTR-2B data without running matching.
    Returns parsed entries for preview before matching.
    """
    _get_user_id(credentials)

    try:
        entries = parse_gstr2b(request.gstr2b_data)
    except Exception as e:
        logger.error(f"GSTR-2B parsing failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse GSTR-2B data: {str(e)}")

    return {
        "success": True,
        "data": {
            "parsed_entries": entries,
            "total_entries": len(entries),
            "period": request.period,
            "summary": {
                "unique_vendors": len(set(e.get("gstin", "") for e in entries if e.get("gstin"))),
                "total_taxable": round(sum(float(e.get("taxable_value", 0)) for e in entries), 2),
                "total_gst": round(
                    sum(
                        float(e.get("cgst", 0)) + float(e.get("sgst", 0)) + float(e.get("igst", 0))
                        for e in entries
                    ), 2
                ),
            },
        },
    }


# ============================================================
# GET /api/itc-match/results — Get Latest Results
# ============================================================

@router.get("/results", response_model=dict)
async def get_itc_results(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
):
    """Get the latest ITC match results for the user's business."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    if is_mock:
        # MockDB doesn't store ITC results yet
        return {
            "success": True,
            "data": {
                "results": [],
                "total": 0,
                "message": "Run ITC matching first by POSTing to /api/itc-match",
            },
        }

    itc_resp = (
        db.table("itc_matches")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    results = itc_resp.data or []

    return {
        "success": True,
        "data": {
            "results": results,
            "total": len(results),
        },
    }
