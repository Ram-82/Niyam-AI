-- Migration 006: Add storage_key column to documents table.
-- Stores the Supabase Storage object path (or local relative path in dev).
-- Replaces the old file_path column for new uploads.

ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS storage_key text;

CREATE INDEX IF NOT EXISTS idx_documents_storage_key ON public.documents(storage_key);
