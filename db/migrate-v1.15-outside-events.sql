-- ---------------------------------------------------------------------------
-- v1.15 — outside events (GDELT, ACLED) for areas of responsibility
--
-- Run against an existing database ONCE, after v1.14:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.15-outside-events.sql
--
-- A fresh install does not need it. Safe to run twice. Adds a flag to zones,
-- the settings row (off until an admin turns a source on) and the events
-- table. Nothing is fetched until a zone is marked and a source enabled.
-- ---------------------------------------------------------------------------

BEGIN;

ALTER TABLE map_zones ADD COLUMN IF NOT EXISTS outside_events BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS outside_event_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- GDELT. Its terms: free for any use, cite it and link to it. Its rates:
    -- the event files are published every 15 minutes (polling more often finds
    -- nothing new), and its API asks for no more than one request every five
    -- seconds — applied here to every request this server makes to GDELT.
    -- Those two floors are CHECKs, so no setting can go under them.
    gdelt_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    gdelt_interval_minutes INTEGER NOT NULL DEFAULT 15 CHECK (gdelt_interval_minutes BETWEEN 15 AND 10080),
    gdelt_request_spacing_seconds NUMERIC(6,1) NOT NULL DEFAULT 5
        CHECK (gdelt_request_spacing_seconds BETWEEN 5 AND 3600),
    -- How far back to fill in when it first comes online or has been offline:
    -- one file per 15 minutes, so 24 h is 96 small files.
    gdelt_backfill_hours INTEGER NOT NULL DEFAULT 24 CHECK (gdelt_backfill_hours BETWEEN 0 AND 168),
    -- CAMEO root codes kept (comma-separated, two digits). The default is the
    -- conflict end of the scale: threats, protest, force posture, coercion
    -- (arrests), assault, fighting, mass violence.
    gdelt_root_codes TEXT NOT NULL DEFAULT '13,14,15,17,18,19,20',
    -- Events reported by fewer distinct sources are dropped (1 keeps all).
    gdelt_min_sources INTEGER NOT NULL DEFAULT 1 CHECK (gdelt_min_sources BETWEEN 1 AND 100),
    -- Only events placed at a city or finer: a state- or country-level place
    -- is that area's centre, which would pile every "Maryland" story onto one
    -- point in the middle of the state.
    gdelt_city_only BOOLEAN NOT NULL DEFAULT TRUE,
    gdelt_last_file TEXT,               -- the last 15-minute file read (YYYYMMDDHHMMSS)
    gdelt_last_poll_at TIMESTAMPTZ,
    gdelt_last_error TEXT,
    -- ACLED. Needs a myACLED account at a level with API access (Research and
    -- up); its licence decides what may be kept. OAuth: the password is used
    -- only to get a token, and never leaves the server's API.
    acled_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    acled_username TEXT,
    acled_password TEXT,
    acled_interval_minutes INTEGER NOT NULL DEFAULT 1440 CHECK (acled_interval_minutes BETWEEN 60 AND 10080),
    acled_request_spacing_seconds NUMERIC(6,1) NOT NULL DEFAULT 2
        CHECK (acled_request_spacing_seconds BETWEEN 1 AND 3600),
    acled_backfill_days INTEGER NOT NULL DEFAULT 30 CHECK (acled_backfill_days BETWEEN 1 AND 365),
    acled_token TEXT,
    acled_token_expires TIMESTAMPTZ,
    acled_last_poll_at TIMESTAMPTZ,
    acled_last_error TEXT,
    -- Unread and dismissed events older than this are deleted; ones sent to
    -- Documents are kept (the document is the record).
    retention_days INTEGER NOT NULL DEFAULT 90 CHECK (retention_days BETWEEN 1 AND 3650),
    -- Set by "Pull now": the worker treats the source as due.
    pull_requested_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO outside_event_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS outside_events (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('gdelt', 'acled')),
    source_id TEXT NOT NULL,            -- GLOBALEVENTID / event_id_cnty
    occurred_on DATE,
    reported_at TIMESTAMPTZ,            -- when the source added it
    title TEXT NOT NULL,
    category TEXT,                      -- CAMEO root / ACLED event type, in words
    code TEXT,                          -- CAMEO event code / ACLED sub-event type
    actor1 TEXT,
    actor2 TEXT,
    place TEXT,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    precision TEXT,                     -- 'city', 'state', 'country', ACLED's geo_precision
    url TEXT,                           -- the article (GDELT); ACLED names its sources instead
    sources_named TEXT,                 -- ACLED's source list
    num_sources INTEGER,
    num_articles INTEGER,
    tone REAL,
    goldstein REAL,
    fatalities INTEGER,
    notes TEXT,
    -- The zones it fell inside when it was pulled.
    zone_ids INTEGER[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'read', 'dismissed', 'sent')),
    attachment_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL,
    sent_by INTEGER REFERENCES users(id),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_outside_events_recent ON outside_events (occurred_on DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_outside_events_status ON outside_events (status);
CREATE INDEX IF NOT EXISTS idx_outside_events_zones ON outside_events USING GIN (zone_ids);
CREATE INDEX IF NOT EXISTS idx_outside_events_place ON outside_events (lat, lon);

COMMIT;
