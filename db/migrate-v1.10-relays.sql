-- ---------------------------------------------------------------------------
-- v1.10 — team relays
--
-- Run against an existing database ONCE, after v1.9:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.10-relays.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- What it does:
--   * adds field_relays: a tablet a team takes on deployment, which collects
--     the team's phone reports offline and syncs them home later;
--   * adds field_relay_members: whose phones a relay may carry reports for;
--   * adds console_identity: the key the console proves itself with, so a
--     relay syncing over a hotel network can tell the real console from
--     something answering at its address;
--   * lets a field submission say it came through a relay, and from which
--     of that relay's phones.
-- ---------------------------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS field_relays (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    -- SHA-256 of the relay's token, as for a field device. NULL until the
    -- tablet has exchanged its one-time provisioning code.
    token_hash TEXT UNIQUE,
    token_prefix TEXT,
    -- One-time code the tablet scans to fetch its bundle. Hashed; cleared
    -- once used. Valid for 30 minutes.
    provision_hash TEXT UNIQUE,
    provision_expires_at TIMESTAMPTZ,
    -- How long the relay may go without checking in before its key is
    -- dropped. Days. The console offers 1 to 14, default 3.
    keepalive_days INTEGER NOT NULL DEFAULT 3 CHECK (keepalive_days BETWEEN 1 AND 14),
    -- Addresses the tablet tries, in order, when the lead presses Sync:
    -- the VPN address first, the office LAN second. A JSON array of URLs.
    addresses JSONB NOT NULL DEFAULT '[]'::jsonb,
    provisioned_at TIMESTAMPTZ,
    last_checkin_at TIMESTAMPTZ,
    last_checkin_ip TEXT,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- 'expired' (no check-in within the keep-alive), 'manual', or
    -- 'reprovisioned' (replaced by a fresh key on return).
    revoke_reason TEXT,
    submission_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS field_relay_members (
    relay_id INTEGER NOT NULL REFERENCES field_relays(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (relay_id, user_id)
);

CREATE TABLE IF NOT EXISTS console_identity (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- ECDSA P-256, PKCS#8 PEM. Generated on first use. Signs only the
    -- relay challenge ("humint-relay-hello:v1:" + nonce), nothing else.
    private_key_pem TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS
    relay_id INTEGER REFERENCES field_relays(id) ON DELETE SET NULL;
-- The relay's own number for this report, and for the phone that sent it.
-- Together with relay_id they make a retried sync land as the same row.
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relay_submission_id INTEGER;
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relay_device_id INTEGER;
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relay_label TEXT;
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relayed_at TIMESTAMPTZ;
-- The team lead's priority tags and note, carried home from the relay.
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relay_priorities JSONB;
ALTER TABLE field_submissions ADD COLUMN IF NOT EXISTS relay_note TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_field_submissions_relay
    ON field_submissions (relay_id, relay_submission_id)
    WHERE relay_id IS NOT NULL AND relay_submission_id IS NOT NULL;

-- The audit log has to be able to say "a relay did this".
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_actor_kind_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_actor_kind_check
    CHECK (actor_kind IN ('user', 'system', 'anonymous', 'device', 'relay'));

COMMIT;
