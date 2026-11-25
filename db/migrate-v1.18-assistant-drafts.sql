-- ---------------------------------------------------------------------------
-- v1.18 — the assistant prepares drafts (reports, priorities, outside events
-- to Documents) that a person applies
--
-- Run against an existing database ONCE, after v1.17:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.18-assistant-drafts.sql
--
-- A fresh install does not need it. Safe to run twice.
-- ---------------------------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS assistant_drafts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- The answer it was prepared in (set when the answer is saved).
    message_id INTEGER REFERENCES assistant_messages(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('report', 'priority', 'outside_to_document', 'link')),
    payload JSONB NOT NULL,
    summary TEXT NOT NULL,
    -- pending: waiting for the person; applied / discarded: their decision;
    -- queued: a proposed link, sent to the Review queue (decided there).
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'discarded', 'queued')),
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_assistant_drafts_message ON assistant_drafts (message_id);
CREATE INDEX IF NOT EXISTS idx_assistant_drafts_user ON assistant_drafts (user_id, status);

COMMIT;
