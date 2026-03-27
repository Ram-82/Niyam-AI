-- Migration 002: Fix RLS policies — replace permissive `using (true)` with
-- proper tenant isolation based on business_id / user_id.

-- Helper functions
create or replace function auth.current_user_id()
returns uuid as $$
  select coalesce(
    current_setting('request.jwt.claims', true)::json->>'sub',
    '00000000-0000-0000-0000-000000000000'
  )::uuid;
$$ language sql stable;

create or replace function auth.current_business_id()
returns uuid as $$
  select business_id from public.users where id = auth.current_user_id();
$$ language sql stable;

-- Drop all old permissive policies
DROP POLICY IF EXISTS "Users can view their own profile" ON public.users;
DROP POLICY IF EXISTS "Users can view their own business" ON public.businesses;
DROP POLICY IF EXISTS "Users can view their own deadlines" ON public.compliance_deadlines;
DROP POLICY IF EXISTS "Users can manage their own deadlines" ON public.compliance_deadlines;
DROP POLICY IF EXISTS "Users can view their own GST filings" ON public.gst_filings;
DROP POLICY IF EXISTS "Users can manage their own GST filings" ON public.gst_filings;
DROP POLICY IF EXISTS "Users can manage their own documents" ON public.documents;
DROP POLICY IF EXISTS "Users can manage their own invoices" ON public.invoices;
DROP POLICY IF EXISTS "Users can manage their own compliance flags" ON public.compliance_flags;
DROP POLICY IF EXISTS "Users can manage their own ITC matches" ON public.itc_matches;

-- Create proper tenant-isolated policies
CREATE POLICY "Users can view own profile" ON public.users FOR SELECT USING (id = auth.current_user_id());
CREATE POLICY "Users can update own profile" ON public.users FOR UPDATE USING (id = auth.current_user_id());

CREATE POLICY "Users can view own business" ON public.businesses FOR SELECT USING (id = auth.current_business_id());
CREATE POLICY "Users can update own business" ON public.businesses FOR UPDATE USING (id = auth.current_business_id());

CREATE POLICY "Users can view own deadlines" ON public.compliance_deadlines FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own deadlines" ON public.compliance_deadlines FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own deadlines" ON public.compliance_deadlines FOR UPDATE USING (business_id = auth.current_business_id());
CREATE POLICY "Users can delete own deadlines" ON public.compliance_deadlines FOR DELETE USING (business_id = auth.current_business_id());

CREATE POLICY "Users can view own GST filings" ON public.gst_filings FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own GST filings" ON public.gst_filings FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own GST filings" ON public.gst_filings FOR UPDATE USING (business_id = auth.current_business_id());

CREATE POLICY "Users can view own documents" ON public.documents FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can upload own documents" ON public.documents FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own documents" ON public.documents FOR UPDATE USING (business_id = auth.current_business_id());

CREATE POLICY "Users can view own invoices" ON public.invoices FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own invoices" ON public.invoices FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own invoices" ON public.invoices FOR UPDATE USING (business_id = auth.current_business_id());

CREATE POLICY "Users can view own compliance flags" ON public.compliance_flags FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own compliance flags" ON public.compliance_flags FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own compliance flags" ON public.compliance_flags FOR UPDATE USING (business_id = auth.current_business_id());

CREATE POLICY "Users can view own ITC matches" ON public.itc_matches FOR SELECT USING (business_id = auth.current_business_id());
CREATE POLICY "Users can manage own ITC matches" ON public.itc_matches FOR INSERT WITH CHECK (business_id = auth.current_business_id());
CREATE POLICY "Users can update own ITC matches" ON public.itc_matches FOR UPDATE USING (business_id = auth.current_business_id());
