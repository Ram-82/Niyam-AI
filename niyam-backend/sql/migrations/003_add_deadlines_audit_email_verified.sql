-- Migration 003: Add tables and columns introduced after initial schema
-- Adds: deadlines table, audit_logs table, users.email_verified column

-- ============================================================
-- 1. users.email_verified column
-- ============================================================
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS email_verified boolean DEFAULT false;

-- Existing users (created before this migration) are considered verified
UPDATE public.users SET email_verified = true WHERE email_verified IS NULL OR email_verified = false;

-- ============================================================
-- 2. deadlines table (used by TDS/ROC routes instead of compliance_deadlines)
-- The TDS/ROC routes use "deadlines" table name. This mirrors
-- compliance_deadlines but with additional fields for mark-as-filed.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.deadlines (
    id              uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    business_id     uuid REFERENCES public.businesses(id) NOT NULL,
    type            text NOT NULL,           -- gst, tds, roc
    subtype         text,                    -- GSTR-1, TDS-Payment, 24Q (Q1), AOC-4, etc.
    due_date        date NOT NULL,
    description     text,
    filing_portal   text,
    penalty_rate    numeric,
    status          text DEFAULT 'upcoming', -- upcoming, due_soon, overdue, completed
    filed_at        timestamptz,
    challan_number  text,                    -- TDS challan reference
    srn_number      text,                    -- ROC SRN reference
    amount_paid     numeric,
    created_at      timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deadlines_business ON public.deadlines(business_id);
CREATE INDEX IF NOT EXISTS idx_deadlines_type ON public.deadlines(type, due_date);

ALTER TABLE public.deadlines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own deadlines_v2"
    ON public.deadlines FOR SELECT
    USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own deadlines_v2"
    ON public.deadlines FOR INSERT
    WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own deadlines_v2"
    ON public.deadlines FOR UPDATE
    USING (business_id = auth.current_business_id());
CREATE POLICY "Users can delete own deadlines_v2"
    ON public.deadlines FOR DELETE
    USING (business_id = auth.current_business_id());

-- ============================================================
-- 3. audit_logs table
-- ============================================================
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id              uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    business_id     uuid REFERENCES public.businesses(id),
    user_id         uuid,
    action          text NOT NULL,           -- user_signup, invoice_uploaded, etc.
    resource_type   text,                    -- user, invoice, deadline
    resource_id     uuid,
    details         jsonb DEFAULT '{}'::jsonb,
    timestamp       timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_business ON public.audit_logs(business_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON public.audit_logs(action);

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own audit logs"
    ON public.audit_logs FOR SELECT
    USING (business_id = auth.current_business_id());
CREATE POLICY "Users can insert own audit logs"
    ON public.audit_logs FOR INSERT
    WITH CHECK (business_id = auth.current_business_id());

-- ============================================================
-- 4. documents table: make file_path nullable (process-invoice
--    sets it to NULL since temp files are deleted after processing)
-- ============================================================
ALTER TABLE public.documents
    ALTER COLUMN file_path DROP NOT NULL;
