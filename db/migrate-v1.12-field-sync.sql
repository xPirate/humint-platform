-- ---------------------------------------------------------------------------
-- v1.12 — field server → HQ case sync
--
-- Run against an existing database ONCE, after v1.11:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.12-field-sync.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- What it does:
--   * gives every console a stable identity of its own that a backup never
--     carries (a field server seeded from an HQ backup must not claim to BE
--     HQ), and remembers when it was last seeded from a backup;
--   * records each field package exported and each one imported, so the
--     same package cannot be imported twice;
--   * maps records a field server created to the records HQ accepted them
--     as, so a later package — or a relationship in the same one — finds them;
--   * lets the review queue hold proposals from a field server (source
--     'field'), and lets the field inbox hold reports a field server sent.
-- ---------------------------------------------------------------------------

BEGIN;

-- One row. Deliberately left out of backups and never wiped by a restore
-- (see api/backup.py PRESERVED_TABLES): it describes this machine, not the
-- case file it holds.
CREATE TABLE IF NOT EXISTS instance_identity (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    instance_uuid TEXT NOT NULL,
    -- When this console was last loaded from a backup. A field server is
    -- normally seeded from an HQ backup before it deploys; everything it
    -- held at that moment HQ already has, so the first export starts here.
    seeded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Field side: what was sent home, and from when.
CREATE TABLE IF NOT EXISTS field_sync_exports (
    id SERIAL PRIMARY KEY,
    package_id TEXT NOT NULL UNIQUE,
    since TIMESTAMPTZ,                  -- NULL = everything
    exported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    exported_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    counts JSONB
);

-- HQ side: each package taken in.
CREATE TABLE IF NOT EXISTS field_imports (
    id SERIAL PRIMARY KEY,
    package_id TEXT NOT NULL UNIQUE,
    origin_id TEXT NOT NULL,            -- the field server's instance_uuid
    origin_name TEXT,                   -- its INSTANCE_NAME, for people
    exported_at TIMESTAMPTZ,
    since TIMESTAMPTZ,
    imported_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    counts JSONB
);

-- A record the field server made, and the record HQ accepted it as (a new
-- one, or one HQ already had). Keyed by origin, so two field servers that
-- happen to generate the same id never collide.
CREATE TABLE IF NOT EXISTS field_import_map (
    origin_id TEXT NOT NULL,
    field_entity_id TEXT NOT NULL,
    hq_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    import_id INTEGER REFERENCES field_imports(id) ON DELETE SET NULL,
    mapped_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    mapped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_id, field_entity_id)
);

-- The review queue: a fifth source.
ALTER TABLE extraction_suggestions DROP CONSTRAINT IF EXISTS extraction_suggestions_source_check;
ALTER TABLE extraction_suggestions ADD CONSTRAINT extraction_suggestions_source_check
    CHECK (source IN ('extraction', 'signal', 'assistant', 'manual', 'field'));
ALTER TABLE extraction_suggestions ADD COLUMN IF NOT EXISTS
    field_import_id INTEGER REFERENCES field_imports(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_suggestions_field_import
    ON extraction_suggestions (field_import_id) WHERE field_import_id IS NOT NULL;

-- The field inbox: reports a field server wrote, waiting to be promoted.
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS
    field_import_id INTEGER REFERENCES field_imports(id) ON DELETE SET NULL;
-- "origin:report-id:updated-at" — the same version of the same report,
-- imported twice (two packages overlapping), lands as one row.
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS field_origin_ref TEXT;
-- The records the report was linked to on the field server, linked again
-- when it is promoted (see field_sync.link_promoted_report).
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS link_entities JSONB;
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_submissions_origin_ref
    ON field_submissions (field_origin_ref) WHERE field_origin_ref IS NOT NULL;

COMMIT;
