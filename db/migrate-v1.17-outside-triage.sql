-- ---------------------------------------------------------------------------
-- v1.17 — outside events: the model triages incidents
--
-- Run against an existing database ONCE, after v1.16:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.17-outside-triage.sql
--
-- A fresh install does not need it. Safe to run twice. Off until an admin
-- turns it on (Admin → Outside events → Model triage).
-- ---------------------------------------------------------------------------

BEGIN;

ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_is_event BOOLEAN;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_in_area BOOLEAN;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_category TEXT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_severity SMALLINT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_summary TEXT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_reason TEXT;
-- 'model' or 'analyst' (a person's correction, which the model never overwrites).
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_by TEXT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_model TEXT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triaged_at TIMESTAMPTZ;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS triage_error TEXT;
DO $$ BEGIN
    ALTER TABLE outside_events ADD CONSTRAINT outside_triage_severity_range
        CHECK (triage_severity IS NULL OR triage_severity BETWEEN 1 AND 5);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_outside_events_untriaged ON outside_events (id)
    WHERE triaged_at IS NULL AND dup_of IS NULL;

-- A person's corrections, kept as examples the model is shown next time.
CREATE TABLE IF NOT EXISTS outside_triage_corrections (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES outside_events(id) ON DELETE SET NULL,
    zone_ids INTEGER[] NOT NULL DEFAULT '{}',
    text TEXT NOT NULL,                 -- the headline and opening the model read
    model_verdict JSONB,                -- what the model said
    verdict JSONB NOT NULL,             -- what the person said
    corrected_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outside_triage_corrections_recent ON outside_triage_corrections (created_at DESC);

-- What a team cares about in an area, in its own words: the model weighs
-- events against it.
ALTER TABLE map_zones ADD COLUMN IF NOT EXISTS outside_focus TEXT;

ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_model TEXT;   -- NULL: the assistant's model
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_acled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_per_pass INTEGER NOT NULL DEFAULT 20;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_min_severity SMALLINT NOT NULL DEFAULT 2;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_examples INTEGER NOT NULL DEFAULT 8;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS triage_last_error TEXT;
DO $$ BEGIN
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_triage_per_pass_range
        CHECK (triage_per_pass BETWEEN 1 AND 500);
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_triage_min_severity_range
        CHECK (triage_min_severity BETWEEN 1 AND 5);
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_triage_examples_range
        CHECK (triage_examples BETWEEN 0 AND 30);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
