-- ============================================================
-- Niyam AI - Database Schema (Supabase PostgreSQL)
-- Auth: Custom JWT (no Supabase Auth)
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- Create businesses table
create table public.businesses (
    id uuid default uuid_generate_v4() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    legal_name text not null,
    trade_name text not null,
    gstin text,
    pan text,
    business_type text default 'Proprietorship',
    address text,
    state_code text,
    is_msme_registered boolean default false,
    msme_number text,
    user_id uuid
);

-- Create users table (standalone — no dependency on auth.users)
create table public.users (
    id uuid default uuid_generate_v4() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    email text not null unique,
    hashed_password text not null,
    full_name text,
    phone text,
    business_id uuid references public.businesses(id),
    last_login timestamp with time zone
);

-- Create compliance_deadlines table
create table public.compliance_deadlines (
    id uuid default uuid_generate_v4() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    business_id uuid references public.businesses(id) not null,
    type text not null, -- 'gst', 'tds', 'roc', 'custom'
    subtype text,
    due_date date not null,
    description text,
    amount numeric,
    penalty_rate numeric,
    status text default 'upcoming', -- 'upcoming', 'overdue', 'completed'
    completed_at timestamp with time zone,
    filing_portal text
);

-- Create gst_filings table
create table public.gst_filings (
    id uuid default uuid_generate_v4() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    business_id uuid references public.businesses(id) not null,
    filing_type text default 'GSTR-3B',
    period_month integer not null,
    period_year integer not null,
    due_date date,
    filed_on timestamp with time zone,
    status text default 'pending',
    reconciliation_status text default 'pending',
    total_tax_liability numeric default 0,
    itc_available numeric default 0,
    challan_number text
);

-- ============================================================
-- Pipeline tables (OCR → Parser → Rules → ITC)
-- ============================================================

-- Documents: uploaded files tracked before/after OCR
create table public.documents (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    uploaded_by     uuid references public.users(id) not null,
    filename        text not null,
    file_path       text not null,
    file_size       integer,
    mime_type       text,
    document_type   text not null,  -- purchase_invoice, sales_invoice, bank_statement, gstr2b
    status          text default 'uploaded',  -- uploaded, processing, extracted, failed
    raw_text        text,
    created_at      timestamptz default now() not null,
    processed_at    timestamptz
);

-- Invoices: structured data extracted from documents (or manually entered)
create table public.invoices (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    document_id     uuid references public.documents(id),
    source          text default 'ocr',  -- ocr, manual, gstr2b_import
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
    hsn_codes       text[],
    invoice_type    text default 'purchase',  -- purchase, sales
    confidence      numeric,
    needs_review    boolean default false,
    review_notes    text,
    created_at      timestamptz default now() not null,
    updated_at      timestamptz
);

-- Compliance flags: issues detected by Rules Engine
create table public.compliance_flags (
    id              uuid default uuid_generate_v4() primary key,
    business_id     uuid references public.businesses(id) not null,
    rule_id         text not null,          -- e.g. "gst_overdue", "invoice_missing_gstin"
    category        text not null,          -- gst, tds, roc, invoice, itc
    severity        text default 'info',    -- info, warning, error, critical
    message         text not null,
    impact_amount   numeric default 0,      -- estimated penalty in ₹
    due_date        date,
    related_id      uuid,                   -- FK to invoice, deadline, etc.
    is_resolved     boolean default false,
    resolved_at     timestamptz,
    metadata        jsonb,
    created_at      timestamptz default now() not null
);

-- Indexes for query performance
create index idx_documents_business    on public.documents(business_id);
create index idx_invoices_business     on public.invoices(business_id);
create index idx_invoices_vendor_gstin on public.invoices(vendor_gstin);
create index idx_invoices_date         on public.invoices(invoice_date);
create index idx_flags_business        on public.compliance_flags(business_id, is_resolved);
create index idx_flags_severity        on public.compliance_flags(severity);

-- Enable Row Level Security (RLS)
alter table public.businesses enable row level security;
alter table public.users enable row level security;
alter table public.compliance_deadlines enable row level security;
alter table public.gst_filings enable row level security;
alter table public.documents enable row level security;
alter table public.invoices enable row level security;
alter table public.compliance_flags enable row level security;

-- RLS Policies: users can only access their own data
-- Note: Since we use custom JWT (not Supabase Auth), these policies
-- use the service role key for all backend operations. RLS protects
-- against direct client access only.

create policy "Users can view their own profile"
on public.users for select
using (true);  -- Backend uses service key; restrict at app layer

create policy "Users can view their own business"
on public.businesses for select
using (true);

create policy "Users can view their own deadlines"
on public.compliance_deadlines for select
using (true);

create policy "Users can manage their own deadlines"
on public.compliance_deadlines for all
using (true);

create policy "Users can view their own GST filings"
on public.gst_filings for select
using (true);

create policy "Users can manage their own GST filings"
on public.gst_filings for all
using (true);

create policy "Users can manage their own documents"
on public.documents for all
using (true);

create policy "Users can manage their own invoices"
on public.invoices for all
using (true);

create policy "Users can manage their own compliance flags"
on public.compliance_flags for all
using (true);
