-- Migration 004: Add billing plan support
-- Adds plan tracking to users, file retention to documents

-- Add plan field to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ;

-- Index for plan lookups (e.g. aggregate plan distribution)
CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);

-- Ensure documents.file_path allows values (already nullable — this migration
-- documents that file_path now stores the retained filename for download)
-- No schema change needed; column already exists as TEXT nullable.

-- Optional: payments table for Razorpay order tracking
CREATE TABLE IF NOT EXISTS payments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    business_id  UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    order_id     TEXT NOT NULL UNIQUE,
    payment_id   TEXT,
    plan_id      TEXT NOT NULL,
    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
    amount_paise  INTEGER NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'INR',
    status       TEXT NOT NULL DEFAULT 'created', -- created | paid | failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at      TIMESTAMPTZ
);

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own payments"
    ON payments FOR SELECT
    USING (auth.uid() = user_id);
