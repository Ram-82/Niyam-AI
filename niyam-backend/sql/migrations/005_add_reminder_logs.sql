-- Migration 005: Add reminder_logs table for deadline email tracking
-- Prevents duplicate reminder emails per deadline per day.

CREATE TABLE IF NOT EXISTS public.reminder_logs (
    id              uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    deadline_id     uuid NOT NULL,
    sent_date       date NOT NULL,
    created_at      timestamptz DEFAULT now() NOT NULL,
    UNIQUE (deadline_id, sent_date)
);

CREATE INDEX IF NOT EXISTS idx_reminder_logs_deadline ON public.reminder_logs(deadline_id, sent_date);
