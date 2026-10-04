-- ---------------------------------------------------------------------------
-- v1.8 — analyst profiles
--
-- Run against an existing database ONCE, after v1.7:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.8-analyst-profiles.sql
--
-- A fresh install does not need it. Safe to run twice.
-- ---------------------------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT,
    callsign TEXT,
    role_title TEXT,
    status TEXT NOT NULL DEFAULT 'At liberty'
        CHECK (status IN ('At liberty', 'Under duress', 'Incapacitated', 'Deceased', 'Captured')),
    status_note TEXT,
    status_changed_at TIMESTAMPTZ,
    status_changed_by INTEGER REFERENCES users(id),
    contacts JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by INTEGER REFERENCES users(id)
);

COMMIT;
