"""
Shared fixtures for Niyam AI test suite.
"""

import os
import pytest

# Force development mode for tests
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")


@pytest.fixture
def sample_invoice_text():
    """Sample OCR text from a typical Indian GST invoice."""
    return """
    TAX INVOICE
    Mumbai Cotton Mills Pvt Ltd
    GSTIN: 27AAACM7890G1Z3
    123, Textile Market, Andheri East
    Mumbai, Maharashtra - 400069

    Invoice No: TEX/2026/0087
    Invoice Date: 02-Mar-2026
    Place of Supply: Maharashtra (27)

    Bill To:
    Sharma Textiles Pvt Ltd
    GSTIN: 27AABCS1234F1Z5

    Sr  Description         HSN     Qty  Rate      Amount
    1   Cotton Fabric 40s   52051200  50  3000.00   150000.00
    2   Cotton Yarn 30s     52052400  40  2500.00   100000.00

    Taxable Amount:                             ₹2,50,000.00
    CGST @ 9%:                                  ₹22,500.00
    SGST @ 9%:                                  ₹22,500.00
    Total Amount:                               ₹2,95,000.00

    Terms: Payment within 30 days
    """


@pytest.fixture
def sample_invoice_data():
    """Structured invoice data (as returned by the processor)."""
    return {
        "vendor_gstin": "27AAACM7890G1Z3",
        "invoice_number": "TEX/2026/0087",
        "invoice_date": "2026-03-02",
        "vendor_name": "Mumbai Cotton Mills",
        "taxable_value": 250000,
        "total_amount": 295000,
        "gst_breakdown": {"cgst": 22500, "sgst": 22500, "igst": 0},
        "line_items": [
            {"description": "Cotton Fabric 40s", "hsn": "52051200", "quantity": 50, "rate": 3000, "amount": 150000},
            {"description": "Cotton Yarn 30s", "hsn": "52052400", "quantity": 40, "rate": 2500, "amount": 100000},
        ],
    }


@pytest.fixture
def sample_invoices():
    """List of invoice dicts for ITC matching."""
    return [
        {
            "invoice_id": "inv-001",
            "invoice_number": "TEX/2026/0087",
            "invoice_date": "2026-03-02",
            "vendor_gstin": "27AAACM7890G1Z3",
            "taxable_value": 250000,
            "cgst": 22500,
            "sgst": 22500,
            "igst": 0,
            "total_amount": 295000,
        },
        {
            "invoice_id": "inv-002",
            "invoice_number": "BLR/EXP/2026-119",
            "invoice_date": "2026-03-10",
            "vendor_gstin": "29BBBBB5555B2Z6",
            "taxable_value": 180000,
            "cgst": 0,
            "sgst": 0,
            "igst": 32400,
            "total_amount": 212400,
        },
    ]


@pytest.fixture
def sample_gstr2b():
    """GSTR-2B data with one exact match and one missing."""
    return {
        "data": {"docdata": {"b2b": [
            {
                "ctin": "27AAACM7890G1Z3",
                "inv": [{
                    "inum": "TEX/2026/0087",
                    "idt": "2026-03-02",
                    "items": [{"txval": 250000, "camt": 22500, "samt": 22500, "iamt": 0, "csamt": 0}],
                }],
            },
        ]}},
    }


@pytest.fixture
def sample_deadlines():
    """Compliance deadlines for testing."""
    return [
        {
            "type": "gst",
            "subtype": "GSTR-3B",
            "due_date": "2026-03-20",
            "status": "upcoming",
            "penalty_rate": 50,
            "filing_portal": "https://gst.gov.in",
        },
        {
            "type": "gst",
            "subtype": "GSTR-1",
            "due_date": "2026-03-11",
            "status": "upcoming",
            "penalty_rate": 50,
            "filing_portal": "https://gst.gov.in",
        },
        {
            "type": "gst",
            "subtype": "GSTR-9",
            "due_date": "2025-12-31",
            "status": "upcoming",
            "penalty_rate": 50,
        },
    ]
