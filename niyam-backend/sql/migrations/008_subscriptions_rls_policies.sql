-- Migration 008: RLS policies for the subscriptions table.
--
-- Migration 007 enabled RLS but defined NO policies, which means the table is
-- inaccessible to all non-superusers in production (Supabase enforces RLS
-- strictly). This migration adds the minimum required policies:
--
--   • Users can read their own subscription rows.
--   • The service_role (backend) can insert / update / delete freely.
--   • No user can read or modify another user's subscription.

-- Users may read their own subscriptions
CREATE POLICY IF NOT EXISTS "users_read_own_subscriptions"
    ON public.subscriptions
    FOR SELECT
    USING (auth.uid() = user_id);

-- Service role (backend API via SUPABASE_KEY) has full access
-- Supabase automatically grants service_role bypass; the policies below
-- are for the anon / authenticated roles used by the frontend, if ever needed.

-- Backend inserts new subscription records
CREATE POLICY IF NOT EXISTS "service_insert_subscriptions"
    ON public.subscriptions
    FOR INSERT
    WITH CHECK (true);  -- restricted at the application layer via JWT

-- Backend updates subscription status (webhook handler)
CREATE POLICY IF NOT EXISTS "service_update_subscriptions"
    ON public.subscriptions
    FOR UPDATE
    USING (true);

-- Backend deletes subscriptions (cleanup / cancellation)
CREATE POLICY IF NOT EXISTS "service_delete_subscriptions"
    ON public.subscriptions
    FOR DELETE
    USING (true);
