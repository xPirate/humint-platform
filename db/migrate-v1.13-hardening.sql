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
--   * two-factor sign-in: a TOTP secret per user, single-use recovery codes,
--     a per-session "may only set up two-factor" flag, and the admin switch
--     that requires it for everyone;
--   * source protection: a protected Source's true identity in a table of its
--     own, readable by its handlers only; and a read-only "viewer" role.
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

-- ---- two-factor sign-in ------------------------------------------------------

ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_pending_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step BIGINT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS needs_2fa_setup BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS require_2fa BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS user_recovery_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_recovery_codes_user ON user_recovery_codes (user_id);

-- ---- source protection, and the viewer role -------------------------------------

CREATE TABLE IF NOT EXISTS source_identity (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    true_name TEXT NOT NULL,
    notes TEXT,
    protected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    protected_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS source_handlers (
    entity_id TEXT NOT NULL REFERENCES source_identity(entity_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    added_by INTEGER REFERENCES users(id),
    PRIMARY KEY (entity_id, user_id)
);

-- Whatever the role constraint was called, replace it with one that knows
-- 'viewer'.
DO $$
DECLARE c TEXT;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'users'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) ILIKE '%role%'
    LOOP
        EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'analyst', 'viewer'));

COMMIT;
