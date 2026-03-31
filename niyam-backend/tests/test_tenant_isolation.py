"""
Tenant isolation tests.

Verifies that User A cannot access User B's data through any API endpoint.
All routes must scope database queries to the requesting user's business_id,
derived from the JWT — never from user-supplied input.

Test strategy:
  - Pre-populate a shared MockDB with two tenants (A has no data, B has data)
  - Patch app.utils.mock_db.MockDB so all route handlers use that same DB
  - Assert User A gets 404 (not 200 or 403/401) when requesting B's resources,
    so we confirm the resource appears non-existent to the wrong tenant
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Must be set before any app-level imports so config.py picks up the test secret
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")

from app.main import app  # noqa: E402 — env must be set first
from app.utils.mock_db import MockDB  # noqa: E402
from app.utils.security import create_access_token, hash_password  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def two_tenants(tmp_path):
    """
    Return a MockDB pre-populated with two completely separate tenants:
      - Tenant A: user + business, no invoices, no documents
      - Tenant B: user + business, one invoice, one document

    Both users have valid JWTs (created with the test secret key).
    """
    db = MockDB(data_dir=str(tmp_path))

    user_a_id = str(uuid.uuid4())
    biz_a_id  = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    biz_b_id  = str(uuid.uuid4())
    inv_b_id  = str(uuid.uuid4())
    doc_b_id  = str(uuid.uuid4())

    # Businesses
    db.create_business({"id": biz_a_id, "user_id": user_a_id,
                         "legal_name": "Tenant A Corp", "trade_name": "Tenant A"})
    db.create_business({"id": biz_b_id, "user_id": user_b_id,
                         "legal_name": "Tenant B Corp", "trade_name": "Tenant B"})

    # Users
    db.create_user({
        "id": user_a_id, "email": "user_a@example.com",
        "hashed_password": hash_password("PasswordA1!"),
        "full_name": "User A", "phone": None,
        "business_id": biz_a_id, "email_verified": True,
        "plan": "free", "last_login": None,
    })
    db.create_user({
        "id": user_b_id, "email": "user_b@example.com",
        "hashed_password": hash_password("PasswordB2@"),
        "full_name": "User B", "phone": None,
        "business_id": biz_b_id, "email_verified": True,
        "plan": "free", "last_login": None,
    })

    # Invoice belonging exclusively to Tenant B
    db.create_invoice({
        "id": inv_b_id, "business_id": biz_b_id,
        "invoice_number": "B-INV-001", "vendor_gstin": "27AAACM7890G1Z3",
        "taxable_value": 50000, "cgst": 4500, "sgst": 4500,
        "igst": 0, "total_amount": 59000, "needs_review": False,
        "vendor_name": "Vendor B", "invoice_date": "2026-03-01",
    })

    # Document belonging exclusively to Tenant B
    # file_path points to a non-existent file — intentional for upload tests
    db.create_document({
        "id": doc_b_id, "business_id": biz_b_id, "uploaded_by": user_b_id,
        "filename": "b_invoice.pdf", "file_path": "/nonexistent/b_invoice.pdf",
        "file_size": 1024, "mime_type": "application/pdf",
        "document_type": "purchase_invoice", "status": "uploaded",
        "raw_text": None, "created_at": "2026-03-01T00:00:00Z",
    })

    return {
        "db": db,
        "user_a_id": user_a_id, "biz_a_id": biz_a_id,
        "token_a": create_access_token({"sub": user_a_id}),
        "user_b_id": user_b_id, "biz_b_id": biz_b_id,
        "token_b": create_access_token({"sub": user_b_id}),
        "inv_b_id": inv_b_id,
        "doc_b_id": doc_b_id,
    }


# ---------------------------------------------------------------------------
# Invoice isolation
# ---------------------------------------------------------------------------

class TestInvoiceIsolation:
    """User A must not be able to list, read, or modify User B's invoices."""

    def test_user_a_invoice_list_is_empty_when_only_b_has_data(self, two_tenants):
        """GET /api/invoices returns only the requesting tenant's invoices."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get(
                "/api/invoices",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        ids = [inv["id"] for inv in data["invoices"]]
        assert ctx["inv_b_id"] not in ids, (
            "User A must not see User B's invoice in the listing"
        )
        assert data["total"] == 0, "User A should have zero invoices"

    def test_user_b_sees_own_invoice_in_list(self, two_tenants):
        """GET /api/invoices returns User B's own invoice."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get(
                "/api/invoices",
                headers={"Authorization": f"Bearer {ctx['token_b']}"},
            )
        assert resp.status_code == 200
        ids = [inv["id"] for inv in resp.json()["data"]["invoices"]]
        assert ctx["inv_b_id"] in ids, "User B must see their own invoice"

    def test_user_a_cannot_get_user_b_invoice_by_id(self, two_tenants):
        """GET /api/invoices/{id} returns 404 when the invoice belongs to another tenant."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get(
                f"/api/invoices/{ctx['inv_b_id']}",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
            )
        assert resp.status_code == 404, (
            f"User A must receive 404 for User B's invoice, got {resp.status_code}"
        )

    def test_user_b_can_get_own_invoice_by_id(self, two_tenants):
        """GET /api/invoices/{id} succeeds for the owning tenant."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.get(
                f"/api/invoices/{ctx['inv_b_id']}",
                headers={"Authorization": f"Bearer {ctx['token_b']}"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == ctx["inv_b_id"]

    def test_user_a_cannot_update_user_b_invoice(self, two_tenants):
        """PATCH /api/invoices/{id} returns 404 when the invoice belongs to another tenant."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.patch(
                f"/api/invoices/{ctx['inv_b_id']}",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
                json={"invoice_number": "TAMPERED"},
            )
        assert resp.status_code == 404, (
            f"User A must receive 404 when patching User B's invoice, got {resp.status_code}"
        )

    def test_update_by_wrong_tenant_does_not_modify_data(self, two_tenants):
        """Even if the response is wrong, the data must not be altered."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            # Attempt from User A
            client.patch(
                f"/api/invoices/{ctx['inv_b_id']}",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
                json={"invoice_number": "TAMPERED"},
            )
            # Verify User B's invoice is unchanged
            resp = client.get(
                f"/api/invoices/{ctx['inv_b_id']}",
                headers={"Authorization": f"Bearer {ctx['token_b']}"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["invoice_number"] == "B-INV-001", (
            "Invoice must be unmodified after cross-tenant PATCH attempt"
        )


# ---------------------------------------------------------------------------
# Document extraction isolation
# ---------------------------------------------------------------------------

class TestDocumentExtractionIsolation:
    """User A must not be able to trigger OCR/extraction on User B's document."""

    def test_user_a_cannot_extract_user_b_document(self, two_tenants):
        """
        POST /api/extract must return 404 when the document_id belongs to
        a different tenant — not 200, 403, or 500.
        """
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/extract",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
                json={"document_id": ctx["doc_b_id"]},
            )
        assert resp.status_code == 404, (
            f"User A must receive 404 for User B's document, got {resp.status_code}: "
            f"{resp.json()}"
        )

    def test_user_b_extract_own_document_passes_ownership_check(self, two_tenants):
        """
        POST /api/extract for User B's own document passes the ownership check
        and proceeds to the file-read step. Since the file path is intentionally
        non-existent, the error is 404 'file not found on disk' — confirming the
        ownership check succeeded (otherwise we'd never reach the file check).
        """
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/extract",
                headers={"Authorization": f"Bearer {ctx['token_b']}"},
                json={"document_id": ctx["doc_b_id"]},
            )
        # Ownership check passed; fails at file-not-found (expected in this test).
        # The middleware wraps HTTPException as {"error": "...", "code": "HTTP_404"}.
        assert resp.status_code == 404
        body = resp.json()
        error_msg = (body.get("detail") or body.get("error") or "").lower()
        assert "file" in error_msg, (
            "Expected 'file not found on disk' error after ownership check passed; "
            f"got: {body}"
        )

    def test_unauthenticated_extract_is_rejected(self, two_tenants):
        """POST /api/extract without a token returns 403."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp = client.post(
                "/api/extract",
                json={"document_id": ctx["doc_b_id"]},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cross-cutting: data never leaks across tenants
# ---------------------------------------------------------------------------

class TestCrossTenantLeakage:
    """Broader checks: no response body ever contains the other tenant's IDs."""

    def test_invoice_list_never_contains_other_tenant_ids(self, two_tenants):
        """Both tenants' invoice listings are fully disjoint."""
        ctx = two_tenants
        with patch("app.utils.mock_db.MockDB", return_value=ctx["db"]):
            resp_a = client.get(
                "/api/invoices",
                headers={"Authorization": f"Bearer {ctx['token_a']}"},
            )
            resp_b = client.get(
                "/api/invoices",
                headers={"Authorization": f"Bearer {ctx['token_b']}"},
            )

        ids_a = {inv["id"] for inv in resp_a.json()["data"]["invoices"]}
        ids_b = {inv["id"] for inv in resp_b.json()["data"]["invoices"]}

        assert ids_a.isdisjoint(ids_b), (
            f"Invoice lists must be disjoint between tenants. Overlap: {ids_a & ids_b}"
        )
        assert ctx["inv_b_id"] not in ids_a
        assert ctx["inv_b_id"] in ids_b
