-- ---------------------------------------------------------------------------
-- v1.16 — outside events: reading articles in place, and folding duplicates
--
-- Run against an existing database ONCE, after v1.15:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.16-outside-reading.sql
--
-- A fresh install does not need it. Safe to run twice. Events already pulled
-- are checked for duplicates by the worker on its next pass.
-- ---------------------------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS outside_articles (
    url TEXT PRIMARY KEY,
    final_url TEXT,
    title TEXT,
    site TEXT,
    published TEXT,
    body TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    fetched_at TIMESTAMPTZ,
    embedding REAL[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS dup_of BIGINT REFERENCES outside_events(id) ON DELETE SET NULL;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS dup_reason TEXT;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS dedupe_locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS rules_checked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE outside_events ADD COLUMN IF NOT EXISTS headline_checked BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_outside_events_dup ON outside_events (dup_of);
CREATE INDEX IF NOT EXISTS idx_outside_events_url ON outside_events (url);

ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS prefetch_articles BOOLEAN NOT NULL DEFAULT TRUE;
-- Per news site: a polite gap between two requests to the same site.
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS article_spacing_seconds NUMERIC(6,1) NOT NULL DEFAULT 2;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS articles_per_pass INTEGER NOT NULL DEFAULT 60;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS dedupe_rules BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS dedupe_model BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE outside_event_settings ADD COLUMN IF NOT EXISTS dedupe_model_threshold REAL NOT NULL DEFAULT 0.86;
DO $$ BEGIN
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_article_spacing_floor
        CHECK (article_spacing_seconds BETWEEN 1 AND 600);
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_articles_per_pass_range
        CHECK (articles_per_pass BETWEEN 1 AND 1000);
    ALTER TABLE outside_event_settings ADD CONSTRAINT outside_dedupe_threshold_range
        CHECK (dedupe_model_threshold BETWEEN 0.5 AND 0.99);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
