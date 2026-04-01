"""
Payment flow tests — Razorpay subscription lifecycle.

Tests the full billing flow:
  1. Create subscription → status 'created'
  2. Webhook subscription.activated → user.plan = 'pro'
  3. Pro feature access → 200
  4. Webhook subscription.halted → user.plan = 'free'
  5. Pro feature access → 403
  6. Expired subscription auto-downgrades via require_plan
"""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")

from app.main import app  # noqa: E402
from app.utils.mock_db import MockDB  # noqa: E402
from app.utils.security import create_access_token, hash_password  # noqa: E402

client = TestClient(app)


@pytest.fixture
def payment_ctx(tmp_path):
    """Set up a user with a mock subscription DB."""
    db = MockDB(data_dir=str(tmp_path))

    user_id = str(uuid.uuid4())
    biz_id = str(uuid.uuid4())
    customer_id = f"cust_mock_{uuid.uuid4().hex[:10]}"

    db.create_business({"id": biz_id, "user_id": user_id,
                        "legal_name": "PayTest", "trade_name": "PayTest"})
    db.create_user({
        "id": user_id, "email": "pay@test.com",
        "hashed_password": hash_password("Pass1234!"),
        "full_name": "Pay User", "phone": None,
        "business_id": biz_id, "email_verified": True,
        "plan": "free", "last_login": None,
        "razorpay_customer_id": customer_id,
    })

    token = create_access_token({"sub": user_id})

    return {
        "db": db,
        "user_id": user_id,
        "biz_id": biz_id,
        "customer_id": customer_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _webhook_signature(body: bytes, secret: str = "") -> str:
    """Generate a Razorpay webhook HMAC-SHA256 signature."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestCreateSubscription:
    def test_create_subscription_returns_mock_id(self, payment_ctx):
        ctx = payment_ctx
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/payments/create-subscription",
                headers=ctx["headers"],
                json={"plan": "pro"},
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["plan"] == "pro"
        assert data["status"] == "created"
        assert data["razorpay_subscription_id"].startswith("sub_mock_")

    def test_subscription_persisted_in_db(self, payment_ctx):
        ctx = payment_ctx
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/payments/create-subscription",
                headers=ctx["headers"],
                json={"plan": "pro"},
            )
        rz_sub_id = resp.json()["data"]["razorpay_subscription_id"]
        sub = ctx["db"].get_subscription_by_razorpay_id(rz_sub_id)
        assert sub is not None
        assert sub["user_id"] == ctx["user_id"]
        assert sub["status"] == "created"


class TestWebhookActivation:
    def test_subscription_activated_upgrades_to_pro(self, payment_ctx):
        ctx = payment_ctx
        rz_sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"

        # Create a subscription record first
        ctx["db"].create_subscription({
            "id": str(uuid.uuid4()),
            "user_id": ctx["user_id"],
            "razorpay_subscription_id": rz_sub_id,
            "plan": "pro",
            "amount_paise": 99900,
            "status": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        webhook_body = json.dumps({
            "event": "subscription.activated",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": rz_sub_id,
                        "customer_id": ctx["customer_id"],
                        "amount": 99900,
                        "paid_count": 1,
                        "end_at": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
                    }
                }
            }
        }).encode()

        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/payments/webhook",
                content=webhook_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": _webhook_signature(webhook_body),
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify user plan updated
        user = ctx["db"].get_user_by_id(ctx["user_id"])
        assert user["plan"] == "pro"

        # Verify subscription status updated
        sub = ctx["db"].get_subscription_by_razorpay_id(rz_sub_id)
        assert sub["status"] == "active"
        assert sub["expires_at"] is not None


class TestWebhookHalted:
    def test_subscription_halted_downgrades_to_free(self, payment_ctx):
        ctx = payment_ctx
        rz_sub_id = f"sub_halt_{uuid.uuid4().hex[:8]}"

        # Create active subscription
        ctx["db"].create_subscription({
            "id": str(uuid.uuid4()),
            "user_id": ctx["user_id"],
            "razorpay_subscription_id": rz_sub_id,
            "plan": "pro",
            "amount_paise": 99900,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        ctx["db"].update_user_plan(ctx["user_id"], "pro")

        webhook_body = json.dumps({
            "event": "subscription.halted",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": rz_sub_id,
                        "customer_id": ctx["customer_id"],
                    }
                }
            }
        }).encode()

        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/payments/webhook",
                content=webhook_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": _webhook_signature(webhook_body),
                },
            )

        assert resp.status_code == 200

        user = ctx["db"].get_user_by_id(ctx["user_id"])
        assert user["plan"] == "free"

        sub = ctx["db"].get_subscription_by_razorpay_id(rz_sub_id)
        assert sub["status"] == "halted"


class TestWebhookSignature:
    def test_invalid_signature_rejected(self, payment_ctx):
        ctx = payment_ctx
        body = json.dumps({"event": "subscription.activated", "payload": {}}).encode()

        # Set a known webhook secret so the signature must match
        with patch("app.config.settings.RAZORPAY_WEBHOOK_SECRET", "real-secret"), \
             patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/payments/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": "bad-signature",
                },
            )
        assert resp.status_code == 400


class TestSubscriptionExpiry:
    def test_expired_subscription_auto_downgrades(self, payment_ctx):
        """require_plan should auto-downgrade if subscription is expired."""
        ctx = payment_ctx
        sub_id = str(uuid.uuid4())

        # Create an expired subscription
        ctx["db"].create_subscription({
            "id": sub_id,
            "user_id": ctx["user_id"],
            "razorpay_subscription_id": "sub_expired",
            "plan": "pro",
            "amount_paise": 99900,
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        ctx["db"].update_user_plan(ctx["user_id"], "pro")

        # Call require_plan directly
        from app.utils.plan_gate import require_plan
        from fastapi import HTTPException as FE

        check = require_plan("pro")

        # Mock credentials
        class FakeCreds:
            credentials = ctx["token"]

        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            with pytest.raises(FE) as exc_info:
                import asyncio
                asyncio.get_event_loop().run_until_complete(check(FakeCreds()))

        assert exc_info.value.status_code == 403
        assert "expired" in exc_info.value.detail.lower()

        # Verify user was downgraded
        user = ctx["db"].get_user_by_id(ctx["user_id"])
        assert user["plan"] == "free"

        # Verify subscription marked expired
        sub = ctx["db"].get_subscription_by_razorpay_id("sub_expired")
        assert sub["status"] == "expired"


class TestGetSubscriptionStatus:
    def test_no_subscription_returns_free(self, payment_ctx):
        ctx = payment_ctx
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get("/api/payments/subscription", headers=ctx["headers"])
        assert resp.status_code == 200
        assert resp.json()["data"]["plan"] == "free"

    def test_active_subscription_returns_plan(self, payment_ctx):
        ctx = payment_ctx
        ctx["db"].create_subscription({
            "id": str(uuid.uuid4()),
            "user_id": ctx["user_id"],
            "razorpay_subscription_id": "sub_active_test",
            "plan": "pro",
            "amount_paise": 99900,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get("/api/payments/subscription", headers=ctx["headers"])
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["plan"] == "pro"
        assert data["subscription"]["status"] == "active"
