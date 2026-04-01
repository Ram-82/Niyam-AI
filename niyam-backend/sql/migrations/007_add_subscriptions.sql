-- Migration 007: Add subscriptions table for Razorpay billing.

CREATE TABLE IF NOT EXISTS public.subscriptions (
    id                      uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id                 uuid REFERENCES public.users(id) NOT NULL,
    razorpay_subscription_id text,
    razorpay_payment_id     text,
    plan                    text NOT NULL DEFAULT 'pro',
    amount_paise            integer NOT NULL DEFAULT 0,
    status                  text NOT NULL DEFAULT 'created', -- created, active, expired, cancelled, halted
    created_at              timestamptz DEFAULT now() NOT NULL,
    expires_at              timestamptz,
    updated_at              timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON public.subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_razorpay ON public.subscriptions(razorpay_subscription_id);

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

-- Add razorpay_customer_id to users (links Niyam user → Razorpay customer)
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS razorpay_customer_id text;
