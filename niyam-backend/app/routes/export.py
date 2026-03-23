"""
Export Routes — filing-ready data in JSON, Excel, or CSV.

GET /api/export?format=json     → structured JSON export
GET /api/export?format=excel    → multi-sheet Excel workbook (CA-friendly)
GET /api/export?format=csv      → lightweight CSV files (zipped)
GET /api/export/readiness       → filing readiness check only
"""

import io
import logging
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token
from app.services.export_service import ExportService, assess_filing_readiness
from app.services.rules import RulesEngine
from app.services.rules.deadline_rules import generate_deadlines_for_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["Export"])
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


def _get_business(db, is_mock: bool, user_id: str) -> tuple:
    """Returns (business_id, business_dict)."""
    if is_mock:
        user = db.get_user_by_id(user_id)
        if not user:
            return None, {}
        bid = user.get("business_id")
        biz = db.get_business_by_id(bid) if bid else {}
        return bid, biz or {}
    else:
        user_resp = db.table("users").select("business_id").eq("id", user_id).single().execute()
        bid = user_resp.data.get("business_id") if user_resp.data else None
        if not bid:
            return None, {}
        biz_resp = db.table("businesses").select("*").eq("id", bid).single().execute()
        return bid, biz_resp.data or {}


@router.get("", response_class=JSONResponse)
async def export_data(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    format: str = Query("json", regex="^(json|excel|csv)$", description="Export format"),
    period: str = Query(None, description="Filing period (e.g. 'Mar 2026')"),
    clean_only: bool = Query(False, description="Only include clean (non-flagged) invoices"),
    exclude_high_risk: bool = Query(False, description="Exclude critical/error items"),
    include_flagged: bool = Query(True, description="Include flagged items"),
    min_confidence: int = Query(0, ge=0, le=100, description="Minimum confidence threshold"),
):
    """
    Export all processed data in the specified format.

    CA opens this and thinks: "This is clean. I can file this in 10 minutes."
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id, business = _get_business(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    period_label = period or f"{date.today().strftime('%b %Y')}"

    # ---- Fetch data ----
    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        inv_resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = inv_resp.data or []

    # Run Rules Engine for compliance flags
    if is_mock:
        deadlines = generate_deadlines_for_year(date.today().year)
    else:
        dl_resp = db.table("compliance_deadlines").select("*").eq("business_id", business_id).execute()
        deadlines = dl_resp.data or []
        if not deadlines:
            deadlines = generate_deadlines_for_year(date.today().year)

    engine = RulesEngine()
    compliance_report = engine.run_all(deadlines=deadlines, invoices=invoices)
    compliance_flags = compliance_report.get("flags", [])

    # Fetch ITC results if available
    itc_results = []
    itc_financials = None
    if not is_mock:
        itc_resp = (
            db.table("itc_matches").select("*")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(500).execute()
        )
        itc_results = itc_resp.data or []

    # ---- Generate export ----
    service = ExportService()
    result = service.export(
        format=format,
        business=business,
        period=period_label,
        invoices=invoices,
        compliance_flags=compliance_flags,
        itc_results=itc_results,
        itc_financials=itc_financials,
        clean_only=clean_only,
        exclude_high_risk=exclude_high_risk,
        include_flagged=include_flagged,
        min_confidence=min_confidence,
    )

    # ---- Return based on format ----
    if format == "json":
        return {"success": True, "data": result["data"]}

    elif format == "excel":
        filename = f"niyam_export_{period_label.replace(' ', '_')}.xlsx"
        return StreamingResponse(
            io.BytesIO(result["data"]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif format == "csv":
        # Zip all CSV files together
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in result["data"].items():
                zf.writestr(fname, content)
        zip_buffer.seek(0)

        filename = f"niyam_export_{period_label.replace(' ', '_')}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/readiness", response_model=dict)
async def check_filing_readiness(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Quick check: is the data ready for filing?

    Returns blocking issues and clean rate without generating a full export.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id, _ = _get_business(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=404, detail="Business not found for user")

    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
    else:
        inv_resp = db.table("invoices").select("*").eq("business_id", business_id).execute()
        invoices = inv_resp.data or []

    # Compliance flags
    if is_mock:
        deadlines = generate_deadlines_for_year(date.today().year)
    else:
        dl_resp = db.table("compliance_deadlines").select("*").eq("business_id", business_id).execute()
        deadlines = dl_resp.data or []
        if not deadlines:
            deadlines = generate_deadlines_for_year(date.today().year)

    engine = RulesEngine()
    report = engine.run_all(deadlines=deadlines, invoices=invoices)
    flags = report.get("flags", [])

    itc_results = []
    if not is_mock:
        itc_resp = (
            db.table("itc_matches").select("*")
            .eq("business_id", business_id)
            .limit(500).execute()
        )
        itc_results = itc_resp.data or []

    readiness = assess_filing_readiness(invoices, flags, itc_results)

    return {"success": True, "data": readiness}
