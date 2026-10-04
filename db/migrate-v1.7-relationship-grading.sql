-- ---------------------------------------------------------------------------
-- v1.7 — relationships graded 1-6, and links that expire
--
-- Run against an existing database ONCE, after v1.6:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.7-relationship-grading.sql
--
-- A fresh install does not need it. Safe to run twice.
-- ---------------------------------------------------------------------------

BEGIN;

-- Confidence moves from three words to the 1-6 Admiralty credibility scale
-- reports already use. The old words map onto the top of it, which is what
-- they meant: confirmed -> 1, probable -> 2, possible -> 3. Nothing is
-- graded 4-6 by this migration; those are new judgments for an analyst to
-- make, not something to infer.
ALTER TABLE relationships DROP CONSTRAINT IF EXISTS relationships_confidence_check;
ALTER TABLE relationships ALTER COLUMN confidence DROP DEFAULT;
UPDATE relationships SET confidence = CASE confidence
    WHEN 'confirmed' THEN '1'
    WHEN 'probable'  THEN '2'
    WHEN 'possible'  THEN '3'
    ELSE confidence END
 WHERE confidence IN ('confirmed', 'probable', 'possible');
ALTER TABLE relationships ALTER COLUMN confidence SET DEFAULT '3';
ALTER TABLE relationships ADD CONSTRAINT relationships_confidence_check
    CHECK (confidence IN ('1', '2', '3', '4', '5', '6'));

-- The last day a link counts. NULL = does not expire.
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS expires_on DATE;

COMMIT;
