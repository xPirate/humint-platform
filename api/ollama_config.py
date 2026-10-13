"""Runtime overrides for Ollama configuration — the api-service half of the
same logic worker/settings.py implements for the background worker.

This is deliberately a separate file from api/settings.py, not a rename of
it: api/settings.py is the *admin-facing* GET/PATCH /api/admin/ollama-settings
router (reading and writing app_settings), while this module is the small
piece any api-side caller — currently only api/assistant.py, which needs to
build its own OllamaClient for live chat/embed calls — actually needs:
"what's the effective config right now, .env plus any admin override." It's
not imported by api/settings.py itself to avoid coupling the router's
request/response shapes to this plainer dict-returning helper.

Kept logically identical to worker/settings.py's get_effective_ollama_config()
(same ENV_DEFAULTS, same override-if-not-NULL merge, same fail-open behavior
if app_settings doesn't exist yet) so the api and worker services can never
disagree about what "the current Ollama config" means. If you change one,
change the other.
"""

import os

from db import db_cursor

# Must match api/settings.py's ENV_DEFAULTS and worker/settings.py's
# ENV_DEFAULTS (same values, different key prefixes/casing per file's own
# convention) — these are what "no override" falls back to.
ENV_DEFAULTS = {
    "base_url": os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
    "model": os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
    # Blank means "use the assistant model" — see the column comment in
    # db/init.sql. Resolved to a concrete value in get_effective_ollama_config
    # so no caller has to know about the fallback.
    "extract_model": os.environ.get("OLLAMA_EXTRACT_MODEL", ""),
    "embed_model": os.environ.get("OLLAMA_EMBED_MODEL", ""),
    "timeout": int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "180")),
    "enabled": os.environ.get("OLLAMA_ENABLED", "true").lower() == "true",
}


def get_effective_ollama_config() -> dict:
    """Returns {base_url, model, embed_model, timeout, enabled} — an
    app_settings override for a field if one is set, otherwise the .env
    value. Never raises: if app_settings doesn't exist yet (a deployment
    that hasn't run the migration) or the query fails for any reason, this
    falls all the way back to pure .env behavior."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT ollama_base_url, ollama_model, ollama_extract_model, "
                "ollama_embed_model, ollama_enabled, ollama_timeout_seconds "
                "FROM app_settings WHERE id = 1"
            )
            row = cur.fetchone()
    except Exception:
        row = None

    if row is None:
        return _resolve(dict(ENV_DEFAULTS))

    base_url, model, extract_model, embed_model, enabled, timeout = row
    return _resolve({
        "base_url": base_url if base_url is not None else ENV_DEFAULTS["base_url"],
        "model": model if model is not None else ENV_DEFAULTS["model"],
        "extract_model": extract_model if extract_model is not None else ENV_DEFAULTS["extract_model"],
        "embed_model": embed_model if embed_model is not None else ENV_DEFAULTS["embed_model"],
        "enabled": enabled if enabled is not None else ENV_DEFAULTS["enabled"],
        "timeout": timeout if timeout is not None else ENV_DEFAULTS["timeout"],
    })


def _resolve(config: dict) -> dict:
    """Collapse the one fallback this config has, so callers never see a blank.

    An unset extraction model means "use the assistant's". Doing that here
    rather than in OllamaClient keeps the fallback in one place — the
    alternative is every caller remembering it, and one of them eventually
    not."""
    config["extract_model"] = (config.get("extract_model") or "").strip() or config["model"]
    return config


# ---------------------------------------------------------------------------
# The assistant's own settings (v1.11). Kept apart from the dict above because
# that one is splatted straight into OllamaClient(**config); these are about
# how the assistant uses the model, not how to reach it.
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


ASSISTANT_ENV_DEFAULTS = {
    # On by default: a model that cannot think simply ignores it (see
    # assistant_agent.py), and one that can gives noticeably better answers.
    "thinking": _env_bool("ASSISTANT_THINKING", "true"),
    # 8K fits an 8B model on an 8 GB card with room to spare; 16K is
    # comfortable on 12 GB. Ollama's own default is smaller than either, which
    # is how case data used to fall silently out of the prompt.
    "context_tokens": _env_int("ASSISTANT_CONTEXT_TOKENS", 8192, 2048, 131072),
    "max_lookups": _env_int("ASSISTANT_MAX_LOOKUPS", 6, 0, 12),
}


def get_assistant_settings() -> dict:
    """{thinking, context_tokens, max_lookups}: an admin override if set,
    otherwise .env. Never raises; a database that has not had the v1.11
    migration simply gets the .env values."""
    settings = dict(ASSISTANT_ENV_DEFAULTS)
    try:
        with db_cursor() as cur:
            cur.execute("SELECT assistant_thinking, assistant_context_tokens, assistant_max_lookups "
                        "FROM app_settings WHERE id = 1")
            row = cur.fetchone()
    except Exception:
        row = None
    if row:
        for key, value in zip(("thinking", "context_tokens", "max_lookups"), row):
            if value is not None:
                settings[key] = value
    return settings
