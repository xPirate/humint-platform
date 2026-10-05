-- ---------------------------------------------------------------------------
-- v1.9 — zones become records, and routes arrive
--
-- Run against an existing database ONCE, after v1.8:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.9-zones-routes.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- What it does:
--   * adds 'zone' and 'route' to the entity types;
--   * gives every existing map zone a Zone record, and links a zone that was
--     the footprint of an Event to that Event (Event located_at Zone);
--   * adds the route_details table;
--   * lets a field submission carry a route or an area's corners.
-- ---------------------------------------------------------------------------

BEGIN;

ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_entity_type_check;
ALTER TABLE entities ADD CONSTRAINT entities_entity_type_check CHECK (entity_type IN
    ('person', 'organization', 'location', 'event', 'source', 'communication',
     'vehicle', 'record', 'zone', 'route'));

ALTER TABLE retention_policy DROP CONSTRAINT IF EXISTS retention_policy_entity_type_check;
ALTER TABLE retention_policy ADD CONSTRAINT retention_policy_entity_type_check CHECK (entity_type IN
    ('person', 'organization', 'location', 'event', 'source', 'communication',
     'vehicle', 'record', 'zone', 'route'));

ALTER TABLE map_zones ADD COLUMN IF NOT EXISTS
    entity_id TEXT UNIQUE REFERENCES entities(id) ON DELETE CASCADE;

-- One Zone record per existing zone, named and described as the zone was, and
-- created by whoever drew it, when they drew it. The id follows the app's own
-- pattern: zone-<slug>-<6 hex>.
DO $$
DECLARE
    z RECORD;
    new_id TEXT;
    slug TEXT;
BEGIN
    FOR z IN SELECT * FROM map_zones WHERE entity_id IS NULL ORDER BY id LOOP
        slug := left(trim(both '-' from regexp_replace(lower(z.name), '[^a-z0-9]+', '-', 'g')), 40);
        new_id := 'zone-' || CASE WHEN slug = '' THEN '' ELSE slug || '-' END
                  || substr(md5(random()::text || z.id::text), 1, 6);
        INSERT INTO entities (id, entity_type, name, description, created_by, created_at, updated_at)
        VALUES (new_id, 'zone', z.name, z.notes, z.created_by, z.created_at, z.updated_at);
        UPDATE map_zones SET entity_id = new_id WHERE id = z.id;
        IF z.event_id IS NOT NULL THEN
            INSERT INTO relationships (from_entity_id, to_entity_id, relationship_type,
                                       confidence, notes, created_by)
            VALUES (z.event_id, new_id, 'located_at', '1',
                    'The zone drawn for this event.', z.created_by);
        END IF;
    END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS route_details (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    geometry JSONB NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    min_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    length_m DOUBLE PRECISION,
    point_count INTEGER,
    environment TEXT,
    travel_mode TEXT,
    origin TEXT NOT NULL DEFAULT 'drawn' CHECK (origin IN ('drawn', 'imported', 'field')),
    source_file TEXT,
    recorded_from TIMESTAMPTZ,
    recorded_until TIMESTAMPTZ,
    point_times JSONB,
    CHECK (max_lat >= min_lat AND max_lon >= min_lon)
);

CREATE INDEX IF NOT EXISTS idx_route_details_bounds
    ON route_details (min_lat, max_lat, min_lon, max_lon);

ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS geometry JSONB;

COMMIT;
