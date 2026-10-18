-- ---------------------------------------------------------------------------
-- v1.13 — hardening
--
-- Run against an existing database ONCE, after v1.12:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.13-hardening.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- What it does:
--   * lets the worker recover jobs a crash or power cut left half-done: each
--     worker keeps a heartbeat, every job it claims names it, and work held by
--     a worker that has gone quiet goes back in the queue (a document only
--     three times; then it is marked failed with the reason);
-- ---------------------------------------------------------------------------

BEGIN;

-- ---- worker recovery -------------------------------------------------------

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE attachments ADD COLUMN IF NOT EXISTS extraction_claimed_by TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS extraction_started_at TIMESTAMPTZ;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS extraction_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE location_details ADD COLUMN IF NOT EXISTS geocode_claimed_by TEXT;
ALTER TABLE map_packs ADD COLUMN IF NOT EXISTS claimed_by TEXT;

COMMIT;
