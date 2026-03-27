"""
Invoices Route — list and retrieve saved invoices for the authenticated business.

GET  /api/invoices          — list all invoices (paginated)
GET  /api/invoices/{id}     — get a single invoice by ID
PATCH /api/invoices/{id}    — update extracted fields (correction flow)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Invoices"])
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


# ================================================================
# GET /api/invoices
# ================================================================
@router.get("/invoices", response_model=dict)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    needs_review: Optional[bool] = Query(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    List all invoices for the authenticated user's business.

    - **page**: page number (1-based)
    - **page_size**: results per page (max 100)
    - **needs_review**: filter to invoices flagged for manual review
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    if is_mock:
        all_invoices = db.get_invoices_by_business(business_id)
    else:
        query = db.table("invoices").select("*").eq("business_id", business_id).order("created_at", desc=True)
        resp = query.execute()
        all_invoices = resp.data or []

    # Optional filter
    if needs_review is not None:
        all_invoices = [inv for inv in all_invoices if inv.get("needs_review") == needs_review]

    # Pagination
    total = len(all_invoices)
    offset = (page - 1) * page_size
    page_items = all_invoices[offset: offset + page_size]

    return {
        "success": True,
        "data": {
            "invoices": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 1,
        },
    }


# ================================================================
# GET /api/invoices/{invoice_id}
# ================================================================
@router.get("/invoices/{invoice_id}", response_model=dict)
async def get_invoice(
    invoice_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Get a single invoice by ID."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
        invoice = next((inv for inv in invoices if inv.get("id") == invoice_id), None)
    else:
        resp = (
            db.table("invoices")
            .select("*")
            .eq("id", invoice_id)
            .eq("business_id", business_id)  # tenant isolation
            .single()
            .execute()
        )
        invoice = resp.data

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {"success": True, "data": invoice}


# ================================================================
# PATCH /api/invoices/{invoice_id}
# ================================================================
@router.patch("/invoices/{invoice_id}", response_model=dict)
async def update_invoice(
    invoice_id: str,
    body: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Correct extracted fields on an invoice. Only allowed fields can be updated.

    Allowed fields: invoice_number, invoice_date, vendor_name, vendor_gstin,
    taxable_value, cgst, sgst, igst, total_amount, needs_review
    """
    ALLOWED_FIELDS = {
        "invoice_number", "invoice_date", "vendor_name", "vendor_gstin",
        "taxable_value", "cgst", "sgst", "igst", "total_amount", "needs_review",
    }

    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    business_id = _get_business_id(db, is_mock, user_id)
    if not business_id:
        raise HTTPException(status_code=403, detail="No business found for this user")

    # Filter to only allowed fields
    updates = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    if is_mock:
        invoices = db.get_invoices_by_business(business_id)
        invoice = next((inv for inv in invoices if inv.get("id") == invoice_id), None)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        def _update(all_invoices):
            for inv in all_invoices:
                if inv.get("id") == invoice_id and inv.get("business_id") == business_id:
                    inv.update(updates)
                    break
        db._read_modify_write(db.invoices_file, _update)

        # Re-fetch updated record
        updated_invoices = db.get_invoices_by_business(business_id)
        invoice = next((inv for inv in updated_invoices if inv.get("id") == invoice_id), invoice)
    else:
        # Verify ownership before update
        check = (
            db.table("invoices")
            .select("id")
            .eq("id", invoice_id)
            .eq("business_id", business_id)
            .single()
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Invoice not found")

        resp = (
            db.table("invoices")
            .update(updates)
            .eq("id", invoice_id)
            .eq("business_id", business_id)
            .execute()
        )
        invoice = resp.data[0] if resp.data else {**updates, "id": invoice_id}

    logger.info(
        f"invoice updated id={invoice_id} fields={list(updates.keys())} "
        f"user={user_id[:8]}"
    )

    # Audit log
    from app.services.audit_service import audit_log
    audit_log(
        business_id, user_id, "invoice_corrected",
        resource_type="invoice", resource_id=invoice_id,
        details={"corrected_fields": list(updates.keys())},
    )

    return {"success": True, "data": invoice}
