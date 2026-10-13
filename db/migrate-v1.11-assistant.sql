-- ---------------------------------------------------------------------------
-- v1.11 — an assistant that looks things up
--
-- Run against an existing database ONCE, after v1.10:
--
--     docker compose exec -T db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < db/migrate-v1.11-assistant.sql
--
-- A fresh install does not need it. Safe to run twice.
--
-- What it does:
--   * three admin settings for the AI Assistant, beside the Ollama ones:
--     whether a model that can reason is allowed to think before answering,
--     how much text the model reads at once (its context window), and how
--     many lookups it may make per question;
--   * keeps, with each answer, the list of lookups that produced it (and the
--     model's reasoning, when it thought first), so the trail under an answer
--     survives closing the panel.
--
-- Without it the assistant still answers, with the .env defaults, but the
-- three settings cannot be changed on the Admin page and the trail under an
-- answer is not kept.
-- ---------------------------------------------------------------------------

BEGIN;

-- NULL means "use the .env value", like every other column in this row.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS assistant_thinking BOOLEAN;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS assistant_context_tokens INTEGER
    CHECK (assistant_context_tokens IS NULL OR assistant_context_tokens BETWEEN 2048 AND 131072);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS assistant_max_lookups INTEGER
    CHECK (assistant_max_lookups IS NULL OR assistant_max_lookups BETWEEN 0 AND 12);

-- [{"tool", "label", "summary"}, ...] plus the reasoning text; see
-- api/assistant_agent.py. Only ever set on 'assistant' rows.
ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS steps JSONB;

COMMIT;
