"""
Payment Routes — Razorpay subscription billing.

POST /api/payments/create-subscription  — initiate a Razorpay subscription (authenticated)
POST /api/payments/webhook              — Razorpay webhook handler (public, signature-verified)
GET  /api/payments/subscription         — get current user's subscription status
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.config import settings
from app.utils.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payments", tags=["Payments"])
security = HTTPBearer()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

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


def _verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook HMAC-SHA256 signature."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET or settings.RAZORPAY_KEY_SECRET
    if not secret:
        logger.warning("No Razorpay secret configured — skipping signature check in dev")
        return settings.ENVIRONMENT != "production"

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


# ------------------------------------------------------------------
# POST /api/payments/create-subscription
# ------------------------------------------------------------------

class CreateSubscriptionRequest(BaseModel):
    plan: str = "pro"


@router.post("/create-subscription", response_model=dict)
async def create_subscription(
    body: CreateSubscriptionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Create a Razorpay subscription for the authenticated user.

    In production: calls Razorpay API to create a subscription.
    In dev: returns a mock subscription for testing.
    """
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    # Look up user
    if is_mock:
        user = db.get_user_by_id(user_id)
    else:
        resp = db.table("users").select("*").eq("id", user_id).single().execute()
        user = resp.data

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # In production, call Razorpay API to create subscription
    razorpay_sub_id = None
    if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
        try:
            import razorpay
            rz_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

            # Ensure user has a Razorpay customer_id
            customer_id = user.get("razorpay_customer_id")
            if not customer_id:
                cust = rz_client.customer.create({
                    "name": user.get("full_name", "Customer"),
                    "email": user.get("email", ""),
                })
                customer_id = cust["id"]
                if is_mock:
                    def _set_cust(users):
                        for u in users:
                            if u.get("id") == user_id:
                                u["razorpay_customer_id"] = customer_id
                                break
                    db._read_modify_write(db.users_file, _set_cust)
                else:
                    db.table("users").update({"razorpay_customer_id": customer_id}).eq("id", user_id).execute()

            # Create subscription via Razorpay
            if not settings.RAZORPAY_PLAN_ID:
                raise HTTPException(status_code=503, detail="Razorpay plan ID not configured")
            rz_sub = rz_client.subscription.create({
                "plan_id": settings.RAZORPAY_PLAN_ID,
                "customer_id": customer_id,
                "total_count": 12,
            })
            razorpay_sub_id = rz_sub["id"]
        except ImportError:
            logger.warning("razorpay package not installed — using mock subscription")
        except Exception as e:
            logger.error(f"Razorpay subscription creation failed: {e}")
            raise HTTPException(status_code=502, detail="Payment provider error")
    else:
        razorpay_sub_id = f"sub_mock_{uuid.uuid4().hex[:12]}"

    # Persist subscription record
    sub_record = {
        "id": sub_id,
        "user_id": user_id,
        "razorpay_subscription_id": razorpay_sub_id,
        "plan": body.plan,
        "amount_paise": settings.PRO_PLAN_AMOUNT_PAISE,
        "status": "created",
        "created_at": now,
        "expires_at": None,
        "updated_at": now,
    }

    if is_mock:
        db.create_subscription(sub_record)
    else:
        db.table("subscriptions").insert(sub_record).execute()

    return {
        "success": True,
        "data": {
            "subscription_id": sub_id,
            "razorpay_subscription_id": razorpay_sub_id,
            "plan": body.plan,
            "amount_paise": settings.PRO_PLAN_AMOUNT_PAISE,
            "status": "created",
            "razorpay_key_id": settings.RAZORPAY_KEY_ID or None,
        },
    }


# ------------------------------------------------------------------
# POST /api/payments/webhook — Razorpay webhook
# ------------------------------------------------------------------

@router.post("/webhook", response_model=dict)
async def razorpay_webhook(request: Request):
    """
    Handle Razorpay webhook events. Signature-verified.

    Supported events:
      - subscription.activated  → plan = pro
      - subscription.completed  → plan = pro (renewal)
      - subscription.halted     → plan = free
      - subscription.cancelled  → plan = free
      - payment.captured        → update subscription status
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not _verify_webhook_signature(body, signature):
        logger.warning("Razorpay webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    logger.info(f"Razorpay webhook: event={event}")

    db, is_mock = _get_db()

    if event in ("subscription.activated", "subscription.completed"):
        _handle_subscription_activated(payload, db, is_mock)
    elif event in ("subscription.halted", "subscription.cancelled"):
        _handle_subscription_halted(payload, db, is_mock)
    elif event == "payment.captured":
        logger.info("Razorpay webhook: payment.captured — logged (no action needed)")
    else:
        logger.info(f"Razorpay webhook: unhandled event '{event}' — skipping")

    return {"status": "ok"}


def _handle_subscription_activated(payload: dict, db, is_mock: bool):
    """Activate subscription and upgrade user to pro."""
    from app.services.email_service import email_service

    sub_entity = (
        payload.get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )
    rz_sub_id = sub_entity.get("id")
    customer_id = sub_entity.get("customer_id")
    end_at = sub_entity.get("end_at")

    if not rz_sub_id:
        logger.warning("Webhook activated: missing subscription id")
        return

    # Find user via razorpay_customer_id
    user = _find_user_by_customer(db, is_mock, customer_id)
    if not user:
        # Fallback: try to find via existing subscription record
        user = _find_user_via_subscription(db, is_mock, rz_sub_id)
    if not user:
        logger.warning(f"Webhook activated: no user found for customer={customer_id}")
        return

    user_id = user["id"]
    expires_at = datetime.fromtimestamp(end_at, tz=timezone.utc).isoformat() if end_at else None
    now = datetime.now(timezone.utc).isoformat()

    # Update subscription status
    if is_mock:
        subs = db._read_file(db.subscriptions_file)
        found = False
        for s in subs:
            if s.get("razorpay_subscription_id") == rz_sub_id:
                s["status"] = "active"
                s["expires_at"] = expires_at
                s["updated_at"] = now
                found = True
                break
        if found:
            db._write_file(db.subscriptions_file, subs)
        else:
            db.create_subscription({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "razorpay_subscription_id": rz_sub_id,
                "plan": "pro",
                "amount_paise": settings.PRO_PLAN_AMOUNT_PAISE,
                "status": "active",
                "created_at": now,
                "expires_at": expires_at,
                "updated_at": now,
            })
        db.update_user_plan(user_id, "pro")
    else:
        db.table("subscriptions").update({
            "status": "active", "expires_at": expires_at, "updated_at": now,
        }).eq("razorpay_subscription_id", rz_sub_id).execute()
        db.table("users").update({"plan": "pro"}).eq("id", user_id).execute()

    email_service.send_plan_upgrade_email(user.get("email", ""), "pro")
    logger.info(f"Subscription activated: user={user_id[:8]} plan=pro")


def _handle_subscription_halted(payload: dict, db, is_mock: bool):
    """Halt/cancel subscription and downgrade user to free."""
    from app.services.email_service import email_service

    sub_entity = (
        payload.get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )
    rz_sub_id = sub_entity.get("id")
    customer_id = sub_entity.get("customer_id")

    user = _find_user_by_customer(db, is_mock, customer_id)
    if not user:
        user = _find_user_via_subscription(db, is_mock, rz_sub_id)
    if not user:
        logger.warning(f"Webhook halted: no user found for customer={customer_id}")
        return

    user_id = user["id"]
    now = datetime.now(timezone.utc).isoformat()

    if is_mock:
        subs = db._read_file(db.subscriptions_file)
        for s in subs:
            if s.get("razorpay_subscription_id") == rz_sub_id:
                s["status"] = "halted"
                s["updated_at"] = now
                break
        db._write_file(db.subscriptions_file, subs)
        db.update_user_plan(user_id, "free")
    else:
        db.table("subscriptions").update({
            "status": "halted", "updated_at": now,
        }).eq("razorpay_subscription_id", rz_sub_id).execute()
        db.table("users").update({"plan": "free"}).eq("id", user_id).execute()

    email_service.send_plan_downgrade_email(user.get("email", ""))
    logger.info(f"Subscription halted: user={user_id[:8]} plan=free")


# ------------------------------------------------------------------
# GET /api/payments/subscription — current subscription status
# ------------------------------------------------------------------

@router.get("/subscription", response_model=dict)
async def get_subscription_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Get the current user's active subscription (if any)."""
    user_id = _get_user_id(credentials)
    db, is_mock = _get_db()

    if is_mock:
        sub = db.get_active_subscription(user_id)
    else:
        try:
            resp = (
                db.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .eq("status", "active")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            sub = resp.data[0] if resp.data else None
        except Exception:
            sub = None

    if not sub:
        return {"success": True, "data": {"plan": "free", "subscription": None}}

    return {
        "success": True,
        "data": {
            "plan": sub.get("plan", "pro"),
            "subscription": {
                "id": sub.get("id"),
                "status": sub.get("status"),
                "amount_paise": sub.get("amount_paise"),
                "expires_at": sub.get("expires_at"),
                "created_at": sub.get("created_at"),
            },
        },
    }


# ------------------------------------------------------------------
# Lookup helpers
# ------------------------------------------------------------------

def _find_user_by_customer(db, is_mock: bool, customer_id: str):
    if not customer_id:
        return None
    if is_mock:
        return db.find_user_by_razorpay_customer_id(customer_id)
    else:
        try:
            resp = db.table("users").select("*").eq("razorpay_customer_id", customer_id).single().execute()
            return resp.data
        except Exception:
            return None


def _find_user_via_subscription(db, is_mock: bool, rz_sub_id: str):
    """Find user via subscription record when customer_id lookup fails."""
    if not rz_sub_id:
        return None
    if is_mock:
        sub = db.get_subscription_by_razorpay_id(rz_sub_id)
        if sub:
            return db.get_user_by_id(sub["user_id"])
        return None
    else:
        try:
            sub_resp = db.table("subscriptions").select("user_id").eq("razorpay_subscription_id", rz_sub_id).single().execute()
            if sub_resp.data:
                user_resp = db.table("users").select("*").eq("id", sub_resp.data["user_id"]).single().execute()
                return user_resp.data
        except Exception:
            return None
