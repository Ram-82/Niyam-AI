# Niyam AI — MVP Architecture (v1)
# Production-Ready Compliance Intelligence Pipeline
# ============================================================
# Author: Architecture Review
# Date: 2026-03-23
# Scope: Upload → OCR → Structured Data → Rules Engine → Insights → Export
# Timeline: 1–2 weeks
# Constraint: Monolith, no microservices, no unnecessary AI layers
# ============================================================


## 1. SYSTEM ARCHITECTURE — End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Vanilla JS)                        │
│  niyam-frontend/                                                    │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐│
│  │ login.html│  │signup.html│  │dashboard │  │  upload / results   ││
│  │          │  │          │  │  .html    │  │  (new view in       ││
│  │          │  │          │  │  .css     │  │   dashboard.html)   ││
│  │          │  │          │  │  .js      │  │                     ││
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────────┬───────────┘│
│       │              │             │                  │             │
│       └──────────────┴─────────────┴──────────────────┘             │
│                            │  config.js → API_URL                   │
└────────────────────────────┼────────────────────────────────────────┘
                             │ HTTPS (JWT Bearer)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI Monolith)                     │
│  niyam-backend/app/                                                 │
│                                                                     │
│  ┌─────────┐    ┌───────────────────────────────────────────────┐   │
│  │  Auth   │    │              API Routes Layer                 │   │
│  │ (JWT)   │    │  /upload  /extract  /compliance-check         │   │
│  │         │    │  /itc-match  /dashboard/summary  /export      │   │
│  └────┬────┘    └───────────────────┬───────────────────────────┘   │
│       │                             │                               │
│       │         ┌───────────────────┴───────────────────────────┐   │
│       │         │              Services Layer                   │   │
│       │         │                                               │   │
│       │         │  ┌────────────┐  ┌────────────┐              │   │
│       │         │  │ OCR Service│→ │ Data Parser │              │   │
│       │         │  │ (tesseract │  │ (invoice    │              │   │
│       │         │  │  + regex)  │  │  normalizer)│              │   │
│       │         │  └────────────┘  └──────┬─────┘              │   │
│       │         │                         │                     │   │
│       │         │                         ▼                     │   │
│       │         │  ┌────────────┐  ┌────────────┐              │   │
│       │         │  │   Rules    │← │ITC Matching │              │   │
│       │         │  │   Engine   │  │  Service    │              │   │
│       │         │  │(deadlines, │  │(2B vs books)│              │   │
│       │         │  │ penalties) │  │             │              │   │
│       │         │  └──────┬─────┘  └──────┬─────┘              │   │
│       │         │         │               │                     │   │
│       │         │         ▼               ▼                     │   │
│       │         │  ┌─────────────────────────────┐             │   │
│       │         │  │   Dashboard Aggregator      │             │   │
│       │         │  │   (metrics, health score,   │             │   │
│       │         │  │    risk calc, export)        │             │   │
│       │         │  └─────────────────────────────┘             │   │
│       │         └───────────────────────────────────────────────┘   │
│       │                             │                               │
│       │                             ▼                               │
│  ┌────┴─────────────────────────────────────────────────────────┐   │
│  │                    Database Layer                             │   │
│  │   DEV:  MockDB (JSON files)                                  │   │
│  │   PROD: Supabase PostgreSQL                                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### How They Interact

**Frontend → Backend:**
- Every request includes `Authorization: Bearer <jwt>` header
- Frontend calls `CONFIG.API_URL + endpoint`
- File uploads use `multipart/form-data`
- All other calls use JSON

**Backend → Database:**
- `AuthService` already handles user/business CRUD
- New services (OCR, Rules, ITC) write to new tables (documents, invoices, etc.)
- Dashboard Aggregator reads across all tables to compute metrics

**The Pipeline (one user action):**
```
User uploads PDF invoice
  → POST /api/upload (saves file, creates document record)
  → POST /api/extract (OCR runs, parser extracts fields)
  → Structured invoice saved to DB
  → Rules Engine auto-runs: checks deadlines, flags issues
  → ITC Matcher auto-runs: cross-checks against 2B data
  → GET /api/dashboard/summary returns updated metrics
```


## 2. BACKEND MODULES — Responsibilities

### Module 1: OCR Service
**File:** `app/services/ocr_service.py`
**Responsibility:** Take a raw PDF/image → extract text
**How it works:**
- Uses `pytesseract` for image-based documents
- Uses `pdfplumber` (not pdf2image) for native PDFs — faster, no Poppler dependency
- Returns raw extracted text string
- Does NOT parse or interpret — just extracts

```python
class OCRService:
    async def extract_text(file_path: str, file_type: str) -> str:
        """Returns raw text from PDF or image."""
        if file_type == "pdf":
            return self._extract_from_pdf(file_path)
        else:
            return self._extract_from_image(file_path)
```

**Why separated from parser:** OCR is a mechanical step. Parser is business logic. Swapping OCR engines (tesseract → cloud API) should not touch parsing.


### Module 2: Data Parser
**File:** `app/services/data_parser.py`
**Responsibility:** Take raw OCR text → extract structured invoice fields
**How it works:**
- Regex patterns for: GSTIN, invoice number, date, amounts, HSN codes, tax breakdowns
- Validates GSTIN format (already have `validate_gstin()` in security.py)
- Returns a structured `ParsedInvoice` dict
- Confidence scoring: marks fields as "extracted" or "needs_review"

```python
class DataParser:
    def parse_invoice(raw_text: str) -> dict:
        """Extract structured fields from raw OCR text."""
        return {
            "vendor_name": ...,
            "vendor_gstin": ...,
            "invoice_number": ...,
            "invoice_date": ...,
            "taxable_value": ...,
            "cgst": ...,
            "sgst": ...,
            "igst": ...,
            "total_amount": ...,
            "hsn_codes": [...],
            "confidence": 0.85,  # overall extraction confidence
            "needs_review": ["vendor_name"]  # fields that need manual check
        }
```


### Module 3: Rules Engine
**File:** `app/services/rules_engine.py`
**Responsibility:** Apply Indian compliance rules to business data
**How it works:**
- **Deadline rules:** Given business type + registration date → generate all statutory deadlines (GST monthly/quarterly, TDS quarterly, ROC annual)
- **Penalty calculator:** Days overdue × rate per day (GST: ₹50/day, ROC: ₹100-200/day, TDS: 1.5%/month interest)
- **Compliance flags:** Missing filings, mismatched GSTINs, expired registrations
- Pure functions — no DB calls. Takes data in, returns flags out.

```python
class RulesEngine:
    def generate_deadlines(business: dict, year: int) -> list[dict]:
        """Generate all statutory deadlines for a business for a given year."""

    def check_compliance(invoices: list, deadlines: list) -> list[dict]:
        """Return list of compliance flags/issues."""

    def calculate_penalty(deadline_type: str, days_late: int, amount: float) -> float:
        """Calculate penalty for a late filing."""
```


### Module 4: ITC Matching Service
**File:** `app/services/itc_service.py`
**Responsibility:** Match purchase invoices against GSTR-2B data
**How it works:**
- Takes two lists: `book_invoices` (from uploads) and `gstr2b_entries` (manually entered or imported)
- Matches on: GSTIN + invoice number + approximate amount (±₹1 tolerance)
- Produces three buckets: **Matched**, **In books but missing in 2B**, **In 2B but missing in books**
- Calculates reclaimable ITC

```python
class ITCMatchingService:
    def reconcile(book_invoices: list, gstr2b_entries: list) -> dict:
        """
        Returns:
        {
            "matched": [...],
            "missing_in_2b": [...],
            "missing_in_books": [...],
            "total_matched_itc": 112000,
            "potential_recovery": 8200,
            "match_rate": 0.92
        }
        """
```


### Module 5: Dashboard Aggregator
**File:** `app/services/dashboard_service.py`
**Responsibility:** Compute all dashboard metrics from DB state
**How it works:**
- Queries: deadlines, invoices, compliance_flags, itc_records
- Calculates: upcoming count, compliance health %, penalty risk, trend data
- Returns the `DashboardMetrics` model (already defined)

```python
class DashboardService:
    async def get_summary(business_id: str) -> dict:
        """Aggregate all metrics for dashboard display."""

    async def get_health_trend(business_id: str, months: int = 6) -> dict:
        """Monthly compliance health scores for chart."""
```


## 3. API DESIGN — Endpoints

### POST /api/upload
**Module:** OCR Service (file handling)
**Auth:** Bearer JWT required
**Purpose:** Upload a document (invoice PDF/image)

```
Request:
  Content-Type: multipart/form-data
  Body:
    file: <binary>                    (required, max 10MB)
    document_type: "purchase_invoice" | "sales_invoice" | "bank_statement" | "gstr2b"

Response (201):
{
  "success": true,
  "data": {
    "document_id": "uuid",
    "filename": "Invoice_June.pdf",
    "document_type": "purchase_invoice",
    "status": "uploaded",
    "uploaded_at": "2026-03-23T10:00:00Z"
  }
}
```

### POST /api/extract
**Module:** OCR Service → Data Parser
**Auth:** Bearer JWT required
**Purpose:** Run OCR + parsing on an uploaded document

```
Request:
{
  "document_id": "uuid"
}

Response (200):
{
  "success": true,
  "data": {
    "document_id": "uuid",
    "status": "extracted",
    "invoice": {
      "vendor_name": "Office Supplies Inc.",
      "vendor_gstin": "29CCCDD0000C1Z1",
      "invoice_number": "INV-2026-0042",
      "invoice_date": "2026-03-15",
      "taxable_value": 3600.00,
      "cgst": 324.00,
      "sgst": 324.00,
      "igst": 0,
      "total_amount": 4248.00,
      "hsn_codes": ["8471"]
    },
    "confidence": 0.87,
    "needs_review": ["vendor_name"]
  }
}
```

### POST /api/compliance-check
**Module:** Rules Engine
**Auth:** Bearer JWT required
**Purpose:** Run compliance rules against current business state

```
Request:
{
  "business_id": "uuid",           (optional — defaults to user's business)
  "check_type": "all" | "gst" | "tds" | "roc"
}

Response (200):
{
  "success": true,
  "data": {
    "flags": [
      {
        "type": "gst",
        "severity": "warning",
        "message": "GSTR-3B for March 2026 due in 4 days",
        "due_date": "2026-03-27",
        "estimated_penalty": 0
      },
      {
        "type": "gst",
        "severity": "error",
        "message": "2 purchase invoices missing vendor GSTIN",
        "affected_invoices": ["doc-uuid-1", "doc-uuid-2"]
      }
    ],
    "compliance_score": 85.5,
    "penalty_risk": "low",
    "total_estimated_penalty": 0
  }
}
```

### POST /api/itc-match
**Module:** ITC Matching Service
**Auth:** Bearer JWT required
**Purpose:** Reconcile uploaded invoices against GSTR-2B data

```
Request:
{
  "business_id": "uuid",
  "period_month": 3,
  "period_year": 2026
}

Response (200):
{
  "success": true,
  "data": {
    "matched": [
      {
        "vendor_gstin": "27AAAAA0000A1Z5",
        "invoice_number": "INV-001",
        "itc_amount": 12400,
        "status": "matched"
      }
    ],
    "missing_in_2b": [
      {
        "vendor_gstin": "07BBBBB1111B2Z6",
        "invoice_number": "INV-042",
        "itc_amount": 8200,
        "status": "missing_in_2b"
      }
    ],
    "missing_in_books": [],
    "summary": {
      "total_matched_itc": 112000,
      "potential_recovery": 8200,
      "match_rate": 0.92,
      "total_invoices_checked": 48
    }
  }
}
```

### GET /api/dashboard/summary
**Module:** Dashboard Aggregator
**Auth:** Bearer JWT required
**Purpose:** Get all dashboard metrics (replaces current hardcoded stub)

```
Response (200):
{
  "success": true,
  "data": {
    "upcoming_deadlines": 3,
    "next_deadline": "GSTR-3B — Mar 27",
    "compliance_health": 85.5,
    "penalty_risk": "low",
    "total_documents": 24,
    "pending_review": 2,
    "itc_summary": {
      "available": 112000,
      "claimed": 103800,
      "potential_recovery": 8200
    },
    "health_history": [78, 82, 80, 85, 83, 85.5],
    "labels": ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
  }
}
```

### GET /api/export
**Module:** Dashboard Aggregator
**Auth:** Bearer JWT required
**Purpose:** Export compliance data as CSV/PDF

```
Request (query params):
  ?type=compliance_report | itc_reconciliation | deadline_summary
  &format=csv | json
  &period_month=3
  &period_year=2026

Response:
  Content-Type: text/csv (or application/json)
  Content-Disposition: attachment; filename="niyam-compliance-report-2026-03.csv"
  Body: <file content>
```


## 4. DATABASE SCHEMA — New Tables

Extends the existing 4 tables (users, businesses, compliance_deadlines, gst_filings).

### Table: documents
```sql
create table public.documents (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    uploaded_by     uuid references public.users(id) not null,
    filename        text not null,
    file_path       text not null,          -- storage path (local or S3)
    file_size       integer,                -- bytes
    mime_type       text,                   -- application/pdf, image/jpeg
    document_type   text not null,          -- purchase_invoice, sales_invoice, bank_statement, gstr2b
    status          text default 'uploaded', -- uploaded, processing, extracted, failed
    raw_text        text,                   -- OCR output
    created_at      timestamptz default now() not null,
    processed_at    timestamptz
);
```

### Table: invoices
```sql
create table public.invoices (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    document_id     uuid references public.documents(id),  -- source document (nullable for manual entry)
    source          text default 'ocr',     -- ocr, manual, gstr2b_import
    invoice_number  text,
    invoice_date    date,
    vendor_name     text,
    vendor_gstin    text,
    buyer_gstin     text,
    taxable_value   numeric default 0,
    cgst            numeric default 0,
    sgst            numeric default 0,
    igst            numeric default 0,
    cess            numeric default 0,
    total_amount    numeric default 0,
    hsn_codes       text[],                 -- PostgreSQL array
    invoice_type    text default 'purchase', -- purchase, sales
    confidence      numeric,                -- OCR extraction confidence (0-1)
    needs_review    boolean default false,
    review_notes    text,
    created_at      timestamptz default now() not null,
    updated_at      timestamptz
);
```

### Table: compliance_flags
```sql
create table public.compliance_flags (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    flag_type       text not null,          -- missing_gstin, deadline_approaching, itc_mismatch, penalty_risk
    severity        text default 'info',    -- info, warning, error
    category        text not null,          -- gst, tds, roc, invoice
    message         text not null,
    related_id      uuid,                   -- references invoice_id, deadline_id, etc.
    is_resolved     boolean default false,
    resolved_at     timestamptz,
    created_at      timestamptz default now() not null
);
```

### Table: itc_records
```sql
create table public.itc_records (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    period_month    integer not null,
    period_year     integer not null,
    vendor_gstin    text not null,
    invoice_number  text,
    itc_amount      numeric default 0,
    source          text not null,          -- books (from uploaded invoices), gstr2b (from 2B import)
    match_status    text default 'unmatched', -- matched, missing_in_2b, missing_in_books, unmatched
    matched_with    uuid,                   -- references the counterpart itc_record id
    created_at      timestamptz default now() not null
);
```

### Indexes (for query performance)
```sql
create index idx_documents_business   on public.documents(business_id);
create index idx_invoices_business    on public.invoices(business_id);
create index idx_invoices_vendor_gstin on public.invoices(vendor_gstin);
create index idx_invoices_date        on public.invoices(invoice_date);
create index idx_flags_business       on public.compliance_flags(business_id, is_resolved);
create index idx_itc_business_period  on public.itc_records(business_id, period_year, period_month);
create index idx_itc_match            on public.itc_records(vendor_gstin, invoice_number);
```


## 5. EXECUTION ORDER — What to Build First

### Phase 1 (Days 1–4): DATA PIPELINE — OCR + Parser + Upload API
**Build first. Everything else depends on having structured data.**

Why OCR first:
- No invoices in DB → Rules Engine has nothing to check
- No invoices in DB → ITC Matching has nothing to match
- No invoices in DB → Dashboard shows hardcoded stubs
- OCR is the **entry point** of the entire pipeline

Deliverables:
1. `documents` + `invoices` tables (schema migration)
2. `POST /api/upload` — accept file, save to disk, create document record
3. `OCRService.extract_text()` — pytesseract + pdfplumber
4. `DataParser.parse_invoice()` — regex extraction for GSTIN, amounts, dates
5. `POST /api/extract` — run OCR → parser → save invoice to DB
6. Update the existing Upload view in dashboard.html to call real APIs

**Exit criteria:** User uploads a PDF → sees extracted invoice fields → data persisted in DB.

### Phase 2 (Days 5–8): RULES ENGINE + COMPLIANCE CHECK
**Build second. Now that data exists, apply rules.**

Deliverables:
1. `compliance_flags` table
2. `RulesEngine.generate_deadlines()` — statutory deadline generator
3. `RulesEngine.check_compliance()` — flag missing GSTINs, approaching deadlines, overdue items
4. `RulesEngine.calculate_penalty()` — already partially exists in frontend JS, move to backend
5. `POST /api/compliance-check` endpoint
6. Auto-trigger rules after each invoice extraction

**Exit criteria:** After upload, system auto-flags "vendor GSTIN invalid" or "GSTR-3B due in 4 days."

### Phase 3 (Days 9–11): ITC MATCHING
**Build third. Requires invoices (Phase 1) and makes compliance checks richer.**

Deliverables:
1. `itc_records` table
2. `ITCMatchingService.reconcile()` — match books vs 2B
3. `POST /api/itc-match` endpoint
4. Allow GSTR-2B data import (upload CSV or manual entry)
5. Update dashboard to show ITC summary

**Exit criteria:** User sees "₹8,200 ITC recoverable — 2 invoices missing in GSTR-2B."

### Phase 4 (Days 12–14): DASHBOARD + EXPORT
**Build last. Aggregates everything into the UI the user already sees.**

Deliverables:
1. `DashboardService.get_summary()` — replace hardcoded stub with real queries
2. `DashboardService.get_health_trend()` — compliance score over time
3. `GET /api/export` — CSV export of compliance report / ITC reconciliation
4. Wire dashboard.js to fetch real data from all new endpoints
5. Connect the existing Chart.js graphs to real trend data

**Exit criteria:** Dashboard shows real metrics from real uploaded data. Export works.


## FINAL FILE STRUCTURE (Post-MVP)

```
niyam-backend/app/
├── main.py
├── config.py
├── database.py
├── models/
│   ├── user.py            (existing)
│   ├── compliance.py      (existing — extend with flag models)
│   ├── document.py        (NEW — DocumentCreate, DocumentResponse)
│   └── invoice.py         (NEW — InvoiceCreate, InvoiceResponse, ITCRecord)
├── routes/
│   ├── auth.py            (existing)
│   ├── dashboard.py       (existing — update to use DashboardService)
│   ├── upload.py          (NEW — /upload, /extract)
│   ├── compliance.py      (NEW — /compliance-check)
│   ├── itc.py             (NEW — /itc-match)
│   └── export.py          (NEW — /export)
├── services/
│   ├── auth_service.py    (existing)
│   ├── ocr_service.py     (NEW)
│   ├── data_parser.py     (NEW)
│   ├── rules_engine.py    (NEW)
│   ├── itc_service.py     (NEW)
│   └── dashboard_service.py (NEW)
└── utils/
    ├── security.py        (existing)
    └── mock_db.py         (existing)
```

### Summary

| Priority | Module            | Days | Why This Order                          |
|----------|-------------------|------|-----------------------------------------|
| 1        | OCR + Parser      | 4    | Pipeline entry point. No data = no MVP. |
| 2        | Rules Engine      | 4    | Makes uploaded data actionable.         |
| 3        | ITC Matching      | 3    | High-value feature for MSMEs.           |
| 4        | Dashboard + Export | 3    | Aggregation layer — reads everything.   |

Total: ~14 days for one developer working full-time.
