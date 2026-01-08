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
    user_id uuid references auth.users(id)
);

-- Create users table (extends Supabase auth.users)
create table public.users (
    id uuid references auth.users(id) primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    email text not null,
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

-- Enable Row Level Security (RLS)
alter table public.businesses enable row level security;
alter table public.users enable row level security;
alter table public.compliance_deadlines enable row level security;
alter table public.gst_filings enable row level security;

-- Create policies (Simple version for MVP: authenticated users can access their own data)
-- Note: In production, you'd want stricter policies checking user_id match

create policy "Users can view their own business"
on public.businesses for select
using (auth.uid() = user_id);

create policy "Users can insert their own business"
on public.businesses for insert
with check (auth.uid() = user_id);

create policy "Users can view their own profile"
on public.users for select
using (auth.uid() = id);

create policy "Users can insert their own profile"
on public.users for insert
with check (auth.uid() = id);

create policy "Users can update their own profile"
on public.users for update
using (auth.uid() = id);
