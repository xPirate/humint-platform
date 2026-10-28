-- ---------------------------------------------------------------------------
-- v1.14 — usernames ignore case
--
-- Run against an existing database ONCE, after v1.13:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.14-usernames.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- "Thomas" and "thomas", "TPain" and "tpain" are one account: signing in
-- takes either, and a new account cannot take a name that differs from an
-- existing one only in case. Names are still shown as they were typed.
--
-- If two accounts already differ only in case, the older keeps its name and
-- each newer one becomes name-<id> ("thomas-12"), so that every account can
-- still sign in by a name of its own. Each rename is printed (NOTICE) and
-- written to the audit log.
-- ---------------------------------------------------------------------------

BEGIN;

DO $$
DECLARE r RECORD; newname TEXT;
BEGIN
    FOR r IN
        SELECT u.id, u.username FROM users u
        WHERE EXISTS (SELECT 1 FROM users o WHERE lower(o.username) = lower(u.username) AND o.id < u.id)
        ORDER BY u.id
    LOOP
        newname := r.username || '-' || r.id;
        UPDATE users SET username = newname WHERE id = r.id;
        RAISE NOTICE 'username % (account %) clashed with an older account but for case: now %',
                     r.username, r.id, newname;
        INSERT INTO audit_log (actor_kind, action, object_type, object_id, object_label, outcome, detail)
        VALUES ('system', 'user.rename', 'user', r.id::text, newname, 'success',
                jsonb_build_object('from', r.username, 'reason', 'usernames now ignore case (v1.14)'));
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_key ON users (lower(username));

COMMIT;
