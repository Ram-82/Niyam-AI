"""
Billing Route — plan management and Razorpay payment integration.

GET  /api/billing/plan           — current plan + usage
POST /api/billing/create-order   — create Razorpay payment order
POST /api/billing/verify-payment — verify payment signature + activate plan
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["Billing"])
security = HTTPBearer()

# Plan definitions — single source of truth for both backend and frontend
PLANS = {
    "free": {
        "id": "free",
        "name": "Free Trial",
        "invoices_per_month": 10,
        "price_monthly": 0,
        "price_annual": 0,
        "features": ["10 invoices/month", "GST/TDS tracking", "Compliance calendar", "Email alerts"],
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "invoices_per_month": 25,
        "price_monthly": 499,
        "price_annual": 4990,
        "features": ["25 invoices/month", "GST/TDS/ROC tracking", "AI invoice parsing", "Basic dashboard"],
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "invoices_per_month": 100,
        "price_monthly": 1499,
        "price_annual": 14990,
        "features": ["100 invoices/month", "+AI ITC matching", "Bank integration", "Ask Niyam chatbot"],
    },
    "pro": {
        "id": "pro",
        "name": "Compliance Pro",
        "invoices_per_month": -1,  # unlimited
        "price_monthly": 2999,
        "price_annual": 28790,
        "features": ["Unlimited invoices", "CA collaboration", "Advanced reports", "Priority support", "10 users"],
    },
}


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


def _get_user_record(db, is_mock: bool, user_id: str) -> Optional[dict]:
    try:
        if is_mock:
            return db.get_user_by_id(user_id)
        else:
            resp = db.table("users").select("id, business_id, plan, email").eq("id", user_id).single().execute()
            return resp.data
    except Exception as e:
        logger.warning(f"Failed to get user for user={user_id[:8]}: {e}")
        return None


@router.get("/plan", response_model=dict)
async def get_billing_plan(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return the user's current plan, usage stats, and Razorpay public key."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    user = _get_user_record(db, is_mock, user_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not found")

    business_id = user.get("business_id")
    plan_id = user.get("plan", "free") or "free"
    plan = PLANS.get(plan_id, PLANS["free"])

    # Count invoices this month
    month_count = 0
    if business_id:
        try:
            if is_mock:
                month_count = db.get_invoice_count_this_month(business_id)
            else:
                from datetime import date
                first_of_month = date.today().replace(day=1).isoformat()
                resp = (
                    db.table("invoices")
                    .select("id", count="exact")
                    .eq("business_id", business_id)
                    .gte("created_at", first_of_month)
                    .execute()
                )
                month_count = resp.count or 0
        except Exception as e:
            logger.warning(f"Could not count monthly invoices: {e}")

    limit = plan["invoices_per_month"]
    remaining = max(0, limit - month_count) if limit != -1 else -1

    return {
        "success": True,
        "data": {
            "plan": plan,
            "usage": {
                "invoices_this_month": month_count,
                "limit": limit,
                "remaining": remaining,
                "is_unlimited": limit == -1,
            },
            "razorpay_key_id": settings.RAZORPAY_KEY_ID or "",
        },
    }


@router.post("/create-order", response_model=dict)
async def create_razorpay_order(
    body: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Create a Razorpay payment order.

    Body: { plan_id: "starter"|"growth"|"pro", billing_cycle: "monthly"|"annual" }
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    user = _get_user_record(db, is_mock, user_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not found")

    plan_id = body.get("plan_id", "").lower()
    billing_cycle = body.get("billing_cycle", "monthly").lower()

    if plan_id not in PLANS or plan_id == "free":
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    plan = PLANS[plan_id]
    amount_inr = plan["price_annual"] if billing_cycle == "annual" else plan["price_monthly"]
    amount_paise = amount_inr * 100  # Razorpay uses paise (smallest unit)

    # Dev mode: return mock order when Razorpay keys are not configured
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        mock_order_id = f"order_dev_{uuid.uuid4().hex[:16]}"
        logger.info(f"Razorpay not configured — returning mock order for dev. plan={plan_id}")
        return {
            "success": True,
            "data": {
                "order_id": mock_order_id,
                "amount": amount_paise,
                "currency": "INR",
                "plan_id": plan_id,
                "plan_name": plan["name"],
                "billing_cycle": billing_cycle,
                "razorpay_key_id": "rzp_test_placeholder",
                "is_dev_mode": True,
            },
        }

    # Create real Razorpay order via REST API
    try:
        import httpx
        business_id = user.get("business_id", "")
        receipt = f"niyam_{plan_id}_{user_id[:8]}"[:40]
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {
                "user_id": user_id,
                "business_id": str(business_id),
                "plan_id": plan_id,
                "billing_cycle": billing_cycle,
            },
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.razorpay.com/v1/orders",
                json=payload,
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                timeout=15,
            )
        if resp.status_code != 200:
            logger.error(f"Razorpay error: {resp.status_code} {resp.text[:300]}")
            raise HTTPException(status_code=502, detail="Payment gateway error. Please try again.")

        order = resp.json()
        return {
            "success": True,
            "data": {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "plan_id": plan_id,
                "plan_name": plan["name"],
                "billing_cycle": billing_cycle,
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "is_dev_mode": False,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay order creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create payment order")


@router.post("/verify-payment", response_model=dict)
async def verify_razorpay_payment(
    body: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Verify Razorpay payment signature and activate the user's plan.

    Body: { razorpay_order_id, razorpay_payment_id, razorpay_signature, plan_id }
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    user = _get_user_record(db, is_mock, user_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not found")
    business_id = user.get("business_id", "")

    order_id = body.get("razorpay_order_id", "")
    payment_id = body.get("razorpay_payment_id", "")
    signature = body.get("razorpay_signature", "")
    plan_id = body.get("plan_id", "")

    if not order_id or not payment_id or not plan_id:
        raise HTTPException(status_code=400, detail="Missing required payment fields")

    if plan_id not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    # Verify signature (skip for dev mock orders)
    if order_id.startswith("order_dev_"):
        logger.info(f"Dev mode payment accepted: plan={plan_id} user={user_id[:8]}")
    elif settings.RAZORPAY_KEY_SECRET:
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Payment signature verification failed")
    else:
        raise HTTPException(status_code=503, detail="Payment verification not configured")

    # Activate plan
    now = datetime.now(timezone.utc).isoformat()
    try:
        if is_mock:
            db.update_user_plan(user_id, plan_id)
        else:
            db.table("users").update({"plan": plan_id, "plan_updated_at": now}).eq("id", user_id).execute()
    except Exception as e:
        logger.error(f"Failed to activate plan for user={user_id[:8]}: {e}")
        raise HTTPException(status_code=500, detail="Plan activation failed. Contact support.")

    logger.info(f"Plan activated: plan={plan_id} user={user_id[:8]} order={order_id}")

    from app.services.audit_service import audit_log
    audit_log(
        str(business_id), user_id, "plan_upgraded",
        resource_type="billing", resource_id=order_id,
        details={"plan_id": plan_id, "payment_id": payment_id},
    )

    return {
        "success": True,
        "message": f"Plan upgraded to {PLANS[plan_id]['name']}!",
        "data": {"plan_id": plan_id, "plan_name": PLANS[plan_id]["name"]},
    }
