-- Migration 004: Add plan column to users table
-- Tracks the user's subscription tier (free, pro, enterprise, etc.)

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS plan text DEFAULT 'free';
