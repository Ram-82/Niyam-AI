#!/usr/bin/env python3
"""
Niyam AI — Database Migration Script (idempotent)

Run this once against Supabase to create all required tables and indexes.
Safe to re-run: uses IF NOT EXISTS / CREATE INDEX IF NOT EXISTS throughout.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python migrate.py

Or via psycopg2 if you have direct DB access:
    DATABASE_URL=postgresql://... python migrate.py --direct
"""

import os
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ============================================================
# SQL — Tables
# ============================================================

TABLES_SQL = """
-- Users
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name       TEXT,
    business_id     UUID,
    is_active       BOOLEAN DEFAULT TRUE,
    last_login      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Businesses
CREATE TABLE IF NOT EXISTS businesses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name      TEXT NOT NULL,
    trade_name      TEXT,
    gstin           TEXT,
    pan             TEXT,
    business_type   TEXT,
    state           TEXT,
    owner_id        UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Documents (uploaded files)
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID NOT NULL REFERENCES businesses(id),
    uploaded_by     UUID REFERENCES users(id),
    filename        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    file_size       INTEGER,
    mime_type       TEXT,
    document_type   TEXT,
    status          TEXT DEFAULT 'uploaded',
    raw_text        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

-- Invoices (normalized from OCR)
CREATE TABLE IF NOT EXISTS invoices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID NOT NULL REFERENCES businesses(id),
    document_id     UUID REFERENCES documents(id),
    source          TEXT DEFAULT 'ocr',
    invoice_number  TEXT,
    invoice_date    DATE,
    vendor_name     TEXT,
    vendor_gstin    TEXT,
    taxable_value   NUMERIC(15,2) DEFAULT 0,
    cgst            NUMERIC(15,2) DEFAULT 0,
    sgst            NUMERIC(15,2) DEFAULT 0,
    igst            NUMERIC(15,2) DEFAULT 0,
    total_amount    NUMERIC(15,2) DEFAULT 0,
    hsn_codes       JSONB DEFAULT '[]',
    invoice_type    TEXT DEFAULT 'purchase',
    confidence      NUMERIC(5,2) DEFAULT 0,
    needs_review    BOOLEAN DEFAULT FALSE,
    review_notes    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ITC Match Records (from reconciler)
CREATE TABLE IF NOT EXISTS itc_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID NOT NULL REFERENCES businesses(id),
    invoice_id      UUID REFERENCES invoices(id),
    invoice_number  TEXT,
    vendor_gstin    TEXT,
    match_type      TEXT,
    severity        TEXT,
    action_type     TEXT,
    eligible_itc    NUMERIC(15,2) DEFAULT 0,
    claimed_itc     NUMERIC(15,2) DEFAULT 0,
    itc_at_risk     NUMERIC(15,2) DEFAULT 0,
    recovery_priority TEXT,
    confidence_score INTEGER DEFAULT 0,
    action_required TEXT,
    due_date        DATE,
    period          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Compliance Flags (from Rules Engine)
CREATE TABLE IF NOT EXISTS compliance_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID NOT NULL REFERENCES businesses(id),
    rule_id         TEXT NOT NULL,
    category        TEXT,
    severity        TEXT NOT NULL,
    message         TEXT NOT NULL,
    action_required TEXT,
    impact_amount   NUMERIC(15,2) DEFAULT 0,
    due_date        DATE,
    resolved        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Compliance Deadlines (statutory calendar)
CREATE TABLE IF NOT EXISTS compliance_deadlines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id     UUID,
    type            TEXT NOT NULL,
    subtype         TEXT,
    due_date        DATE NOT NULL,
    status          TEXT DEFAULT 'upcoming',
    penalty_rate    NUMERIC(10,2) DEFAULT 0,
    filing_portal   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""

# ============================================================
# SQL — Indexes (named so IF NOT EXISTS works correctly)
# ============================================================

INDEXES_SQL = """
-- invoices: fast lookup by GSTIN and invoice number (ITC reconciliation hot path)
CREATE INDEX IF NOT EXISTS idx_invoices_gstin
    ON invoices (vendor_gstin);

CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number
    ON invoices (invoice_number);

CREATE INDEX IF NOT EXISTS idx_invoices_business_id
    ON invoices (business_id);

-- itc_records: lookup by invoice_id (join from invoices table)
CREATE INDEX IF NOT EXISTS idx_itc_records_invoice_id
    ON itc_records (invoice_id);

CREATE INDEX IF NOT EXISTS idx_itc_records_business_id
    ON itc_records (business_id);

-- compliance_flags: filter by severity (dashboard top actions query)
CREATE INDEX IF NOT EXISTS idx_compliance_flags_severity
    ON compliance_flags (severity);

-- compliance_flags: filter by due_date for timeline
CREATE INDEX IF NOT EXISTS idx_compliance_flags_due_date
    ON compliance_flags (due_date);

CREATE INDEX IF NOT EXISTS idx_compliance_flags_business_id
    ON compliance_flags (business_id);

-- documents: status filter (find pending/failed docs)
CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (status);

CREATE INDEX IF NOT EXISTS idx_documents_business_id
    ON documents (business_id);

-- users: email lookup (login hot path)
CREATE INDEX IF NOT EXISTS idx_users_email
    ON users (email);
"""

# ============================================================
# Runners
# ============================================================

def run_via_supabase(supabase_url: str, supabase_key: str):
    """
    Run migration via Supabase REST API using the PostgREST /rpc endpoint.
    Requires service_role key (not anon key) for DDL access.
    """
    try:
        from supabase import create_client, Client
    except ImportError:
        log.error("supabase package not installed. Run: pip install supabase")
        sys.exit(1)

    client: Client = create_client(supabase_url, supabase_key)

    all_sql = TABLES_SQL + "\n" + INDEXES_SQL

    # Supabase JS/Python client doesn't expose raw DDL directly.
    # We use the postgrest /rpc execute endpoint via httpx.
    try:
        import httpx
    except ImportError:
        log.error("httpx not installed. Run: pip install httpx")
        sys.exit(1)

    db_url = supabase_url.rstrip("/") + "/rest/v1/rpc/exec_sql"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }

    # Note: exec_sql RPC must be created in Supabase if it doesn't exist.
    # Fallback: split statements and run each one.
    log.info("Running migration via Supabase...")

    # Split and execute each statement individually
    statements = [s.strip() for s in all_sql.split(";") if s.strip() and not s.strip().startswith("--")]
    ok = 0
    for stmt in statements:
        resp = httpx.post(db_url, json={"sql": stmt + ";"}, headers=headers, timeout=30)
        if resp.status_code not in (200, 201, 204):
            # Some statements may error if already applied — log but continue
            log.warning(f"Statement warning ({resp.status_code}): {resp.text[:120]}")
        else:
            ok += 1

    log.info(f"Migration via Supabase: {ok}/{len(statements)} statements applied.")


def run_via_psycopg2(database_url: str):
    """Run migration directly via psycopg2 (requires direct DB access)."""
    try:
        import psycopg2
    except ImportError:
        log.error("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()

    all_sql = TABLES_SQL + "\n" + INDEXES_SQL
    statements = [s.strip() for s in all_sql.split(";") if s.strip() and not s.strip().startswith("--")]
    ok = 0
    for stmt in statements:
        try:
            cur.execute(stmt)
            ok += 1
        except Exception as e:
            log.warning(f"Statement skipped: {e}")

    cur.close()
    conn.close()
    log.info(f"Migration via psycopg2: {ok}/{len(statements)} statements applied.")


def print_sql():
    """Print migration SQL to stdout (for manual application)."""
    print("-- Niyam AI Migration SQL (idempotent)")
    print("-- Apply in Supabase SQL Editor or via psql")
    print()
    print(TABLES_SQL)
    print(INDEXES_SQL)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Niyam AI database migration")
    parser.add_argument("--direct", action="store_true", help="Use psycopg2 with DATABASE_URL")
    parser.add_argument("--print", action="store_true", dest="print_sql", help="Print SQL only, do not execute")
    args = parser.parse_args()

    if args.print_sql:
        print_sql()
        sys.exit(0)

    if args.direct:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            log.error("DATABASE_URL environment variable not set")
            sys.exit(1)
        run_via_psycopg2(db_url)
    else:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        supabase_key = os.getenv("SUPABASE_KEY", "").strip()
        if not supabase_url or not supabase_key:
            log.error("SUPABASE_URL and SUPABASE_KEY must be set (use service_role key for DDL)")
            log.info("Tip: Run with --print to get the SQL for manual application in Supabase SQL Editor")
            sys.exit(1)
        run_via_supabase(supabase_url, supabase_key)
