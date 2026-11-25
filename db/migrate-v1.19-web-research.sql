-- ---------------------------------------------------------------------------
-- v1.19 — web research for the assistant (off until an admin turns it on)
--
-- Run against an existing database ONCE, after v1.18:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.19-web-research.sql
--
-- A fresh install does not need it. Safe to run twice.
-- ---------------------------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS web_research_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    -- searxng: a SearXNG instance (self-hosted; JSON output on);
    -- brave: Brave's Search API (a key); duckduckgo: its plain-HTML page
    -- (no install, no key; for light use).
    provider TEXT NOT NULL DEFAULT 'searxng' CHECK (provider IN ('searxng', 'brave', 'duckduckgo')),
    searxng_url TEXT,
    brave_key TEXT,
    -- Every search and page read goes through it when set: http://, https://,
    -- socks5:// or socks5h:// (Tor: socks5h://127.0.0.1:9050).
    proxy_url TEXT,
    -- Each search is shown to the person and run only when they approve it.
    require_approval BOOLEAN NOT NULL DEFAULT TRUE,
    max_searches INTEGER NOT NULL DEFAULT 4 CHECK (max_searches BETWEEN 1 AND 20),
    max_pages INTEGER NOT NULL DEFAULT 4 CHECK (max_pages BETWEEN 0 AND 20),
    -- Who may use it: 'admins' or 'analysts' (admins and analysts).
    allowed TEXT NOT NULL DEFAULT 'analysts' CHECK (allowed IN ('admins', 'analysts')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
INSERT INTO web_research_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

ALTER TABLE assistant_drafts DROP CONSTRAINT IF EXISTS assistant_drafts_kind_check;
ALTER TABLE assistant_drafts ADD CONSTRAINT assistant_drafts_kind_check
    CHECK (kind IN ('report', 'priority', 'outside_to_document', 'link', 'web_to_document'));

COMMIT;
