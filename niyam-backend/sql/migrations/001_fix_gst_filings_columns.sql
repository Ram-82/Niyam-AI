-- Migration 001: Add missing columns to gst_filings table
-- These columns exist in the Pydantic model but were missing from the schema,
-- causing insert failures.

ALTER TABLE public.gst_filings
    ADD COLUMN IF NOT EXISTS total_taxable_value numeric DEFAULT 0,
    ADD COLUMN IF NOT EXISTS itc_claimed numeric DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payment_made numeric DEFAULT 0;
