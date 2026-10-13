"""Case-data-aware AI assistant — the app-wide side panel (see the "AI
Assistant" section of docs/DESIGN.md).

Since v1.11 the work happens in assistant_agent.py: the model is given the
read-only lookups in assistant_tools.py and works in a loop until it can
answer. This module is the HTTP side of that — the streaming /ask endpoint
the panel uses, the one-shot /messages kept for scripts, saving each answer
with the trail of lookups behind it, and the audit entry.

The single search below (build_context) is the pre-v1.11 retrieval, still
used when "Lookups per question" is set to 0 or the model cannot call tools.
It has two tiers, chosen per question:

1. Embedding similarity, when OLLAMA_EMBED_MODEL is configured. The question
   itself is embedded via the same Ollama embed endpoint worker/correlate.py
   already uses to embed entities/reports for the correlation queue, then
   compared (plain-Python cosine similarity, same math as correlate.py) against
   every already-embedded entity/report. It can surface a relevant record even
   when the question doesn't share any exact words with it. The lookup loop's
   search uses the same similarity as its fallback when no words match.
2. Keyword fallback, used whenever tier 1 isn't available (no embed model
   configured) or simply turns up nothing above the similarity floor. Plain
   ILIKE matching of the question's meaningful words against entity
   name/description and report title/body, ranked by how many distinct
   keywords matched.

Either way, once a shortlist of entity/report ids is chosen, the actual
context text reuses entities.get_entity() / reports._report_dict() — the same
functions the regular detail-view endpoints use — so the assistant sees the
same shape of data an analyst would see by clicking into that record.

Nothing here ever writes to entities/relationships/reports. The only writes
this module makes are to assistant_messages, which is purely a per-user
conversation log, not case data.
"""

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import assistant_agent
import audit
import auth
import ollama_usage
import entities as entities_module
import reports as reports_module
from db import db_cursor
from ollama_client import OllamaClient
from ollama_config import get_assistant_settings, get_effective_ollama_config

logger = logging.getLogger("api.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# How many prior turns (user+assistant pairs) ride along as conversation
# history on every call, so the model can handle an obvious follow-up
# ("and where was he last seen?") without every question needing to restate
# the subject. Capped rather than sending the whole history: history grows
# unboundedly over a conversation's lifetime and this app has no token-budget
# tracking, so a fixed cap is the simple guard against silently blowing past
# whatever context window the configured model actually has.
HISTORY_TURNS = 6

MAX_CONTEXT_ENTITIES = 5
MAX_CONTEXT_REPORTS = 4
EMBEDDING_SIMILARITY_FLOOR = 0.3  # deliberately lower than correlation's 0.88 — this is "plausibly relevant," not "probably the same thing"
REPORT_BODY_EXCERPT_CHARS = 900

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "is", "are", "was", "were",
    "be", "been", "being", "do", "does", "did", "what", "who", "whom", "whose", "where", "when",
    "why", "how", "which", "this", "that", "these", "those", "with", "about", "tell", "me", "my",
    "know", "we", "us", "our", "you", "your", "i", "it", "its", "as", "from", "any", "all", "there",
    "have", "has", "had", "can", "could", "would", "should", "will", "shall", "please", "info",
    "information", "case", "file",
}

ASSISTANT_SYSTEM_PROMPT = """You are an assistant embedded in a HUMINT/OSINT case-management \
platform, helping an analyst quickly recall or reason about what is already recorded in THEIR \
case file. You are not a general-purpose chatbot and have no knowledge of this case beyond what \
is given to you below as "Relevant case data," retrieved specifically for this question.

Answer using only that case data plus ordinary reasoning over it. If the case data does not \
contain the answer, say so plainly instead of guessing or inventing a name, date, relationship, \
or fact that was not actually provided. Keep answers concise and analyst-facing. Light markdown \
(short paragraphs, a bullet list when genuinely useful) is fine; do not use headers. Never present \
a guess as a confirmed fact, and never fabricate an entity, relationship, or report that was not \
in the provided context."""


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _cosine_similarity(a: list, b: list) -> float:
    """Same plain-Python cosine similarity as worker/correlate.py — kept as
    its own tiny copy here rather than importing across the api/worker
    package boundary (the two services don't share a Python path)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keywords(question: str) -> list[str]:
    """Lowercased, deduplicated, stopword-filtered words of length >= 3, in
    first-seen order, capped at 12 -- plenty for a natural-language question
    and small enough that the keyword fallback query below stays cheap."""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']{2,}", question.lower())
    seen: list[str] = []
    for t in tokens:
        if t in STOPWORDS or t in seen:
            continue
        seen.append(t)
    return seen[:12]


def _embedding_entities(cur, vec: list[float], limit: int) -> list[tuple[float, str]]:
    cur.execute(
        "SELECT id, embedding FROM entities WHERE is_active = TRUE AND embedding IS NOT NULL"
    )
    scored = []
    for entity_id, embedding_json in cur.fetchall():
        try:
            candidate = json.loads(embedding_json)
        except (TypeError, ValueError):
            continue
        score = _cosine_similarity(vec, candidate)
        if score >= EMBEDDING_SIMILARITY_FLOOR:
            scored.append((score, entity_id))
    scored.sort(key=lambda pair: -pair[0])
    return scored[:limit]


def _embedding_reports(cur, vec: list[float], limit: int) -> list[tuple[float, str]]:
    cur.execute("SELECT id, embedding FROM reports WHERE embedding IS NOT NULL")
    scored = []
    for report_id, embedding_json in cur.fetchall():
        try:
            candidate = json.loads(embedding_json)
        except (TypeError, ValueError):
            continue
        score = _cosine_similarity(vec, candidate)
        if score >= EMBEDDING_SIMILARITY_FLOOR:
            scored.append((score, report_id))
    scored.sort(key=lambda pair: -pair[0])
    return scored[:limit]


def _keyword_entities(cur, keywords: list[str], limit: int) -> list[str]:
    if not keywords:
        return []
    patterns = [f"%{k}%" for k in keywords]
    # Over-fetch a wider candidate pool than `limit`, then rank in Python by
    # how many distinct keywords actually matched -- ILIKE ANY() alone can
    # only filter "at least one keyword matched," not rank by how many did.
    cur.execute(
        "SELECT id, name, description FROM entities "
        "WHERE is_active = TRUE AND (name ILIKE ANY(%s) OR description ILIKE ANY(%s)) "
        "LIMIT %s",
        (patterns, patterns, limit * 6),
    )
    scored = []
    for entity_id, name, description in cur.fetchall():
        text = f"{name} {description or ''}".lower()
        score = sum(1 for k in keywords if k in text)
        scored.append((score, entity_id))
    scored.sort(key=lambda pair: -pair[0])
    return [entity_id for _, entity_id in scored[:limit]]


def _keyword_reports(cur, keywords: list[str], limit: int) -> list[str]:
    if not keywords:
        return []
    patterns = [f"%{k}%" for k in keywords]
    cur.execute(
        "SELECT id, title, body_markdown FROM reports "
        "WHERE title ILIKE ANY(%s) OR body_markdown ILIKE ANY(%s) "
        "LIMIT %s",
        (patterns, patterns, limit * 6),
    )
    scored = []
    for report_id, title, body_markdown in cur.fetchall():
        text = f"{title} {body_markdown or ''}".lower()
        score = sum(1 for k in keywords if k in text)
        scored.append((score, report_id))
    scored.sort(key=lambda pair: -pair[0])
    return [report_id for _, report_id in scored[:limit]]


def _entity_context_block(entity: dict) -> str:
    """Renders one entity's dossier (as returned by entities.get_entity) into
    plain text for the prompt -- name/type/description, whichever detail
    fields are actually set, its relationships, and the titles of reports
    that mention it. Deliberately skips attachments: attachment content isn't
    fetched here, and the filename/status alone isn't useful context."""
    lines = [f"### {entity['entity_type'].capitalize()}: {entity['name']} (id: {entity['id']})"]
    if entity.get("description"):
        lines.append(f"Description: {entity['description'][:600]}")
    for key, value in (entity.get("details") or {}).items():
        if value in (None, "", []):
            continue
        label = key.replace("_", " ").capitalize()
        lines.append(f"{label}: {value}")
    if entity.get("relationships"):
        lines.append("Relationships:")
        for rel in entity["relationships"][:12]:
            arrow = "->" if rel["direction"] == "outgoing" else "<-"
            lines.append(
                f"- {arrow} {rel['relationship_type']} {arrow} "
                f"{rel['other_entity_type']}: {rel['other_entity_name']} "
                f"(graded {rel['confidence']}: "
                f"{entities_module.CONFIDENCE_LABELS.get(rel['confidence'], rel['confidence'])}"
                f"{', EXPIRED ' + str(rel['expires_on']) if rel.get('expired') else ''})"
            )
    if entity.get("reports"):
        titles = ", ".join(f'"{r["title"]}"' for r in entity["reports"][:5])
        lines.append(f"Mentioned in report(s): {titles}")
    return "\n".join(lines)


def _report_context_block(report: dict) -> str:
    lines = [
        f"### Report: \"{report['title']}\" (id: {report['id']}, status: {report['status']}, "
        f"credibility: {report.get('credibility_rating') or 'unrated'})"
    ]
    body = (report.get("body_markdown") or "").strip()
    if body:
        excerpt = body[:REPORT_BODY_EXCERPT_CHARS]
        if len(body) > REPORT_BODY_EXCERPT_CHARS:
            excerpt += "…"
        lines.append(f"Body: {excerpt}")
    if report.get("entities"):
        names = ", ".join(e["name"] for e in report["entities"][:10])
        lines.append(f"Linked entities: {names}")
    return "\n".join(lines)


def build_context(cur, ollama: OllamaClient, question: str, user: dict) -> tuple[str, list[dict]]:
    """Returns (context_text, citations). context_text is "" when nothing
    relevant was found (the system prompt still gets sent, so the model is
    still told plainly that no case data matched, rather than silently
    getting no context and no explanation)."""
    vec = ollama.embed(question) if ollama.enabled and ollama.embed_model else None

    entity_ids: list[str] = []
    report_ids: list[str] = []
    if vec is not None:
        entity_ids = [eid for _, eid in _embedding_entities(cur, vec, MAX_CONTEXT_ENTITIES)]
        report_ids = [rid for _, rid in _embedding_reports(cur, vec, MAX_CONTEXT_REPORTS)]

    if not entity_ids and not report_ids:
        keywords = _keywords(question)
        entity_ids = _keyword_entities(cur, keywords, MAX_CONTEXT_ENTITIES)
        report_ids = _keyword_reports(cur, keywords, MAX_CONTEXT_REPORTS)

    blocks = []
    citations = []

    if entity_ids:
        blocks.append("## Entities")
        for entity_id in entity_ids:
            try:
                entity = entities_module.get_entity(entity_id, user=user)
            except HTTPException:
                continue  # archived/deleted between retrieval and now -- just skip it
            blocks.append(_entity_context_block(entity))
            citations.append({
                "kind": "entity", "id": entity_id,
                "label": f"{entity['entity_type'].capitalize()}: {entity['name']}",
            })

    if report_ids:
        blocks.append("## Reports")
        for report_id in report_ids:
            try:
                report = reports_module._report_dict(cur, report_id)
            except HTTPException:
                continue
            blocks.append(_report_context_block(report))
            citations.append({"kind": "report", "id": report_id, "label": f"Report: {report['title']}"})

    return "\n\n".join(blocks), citations


def _load_history(cur, user_id: int) -> list[dict]:
    # Ordered by `id`, not `created_at`: a question and its answer are
    # inserted in the same transaction (see ask_assistant below), and
    # Postgres's now() returns the same value for every statement in one
    # transaction -- so the two rows of a single turn always share an
    # identical created_at and ORDER BY created_at alone has no defined tie-
    # break between them. `id` is a SERIAL, strictly increasing in insertion
    # order, so it's the only column here that's actually reliable to sort by.
    cur.execute(
        "SELECT role, content FROM assistant_messages WHERE user_id = %s "
        "ORDER BY id DESC LIMIT %s",
        (user_id, HISTORY_TURNS * 2),
    )
    rows = cur.fetchall()
    rows.reverse()  # query fetched newest-first to bound the scan; the model needs oldest-first
    return [{"role": role, "content": content} for role, content in rows]


@router.get("/messages")
def list_messages(user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        try:
            # See _load_history's comment above on why `id`, not `created_at`.
            cur.execute(
                "SELECT id, role, content, citations, created_at, steps FROM assistant_messages "
                "WHERE user_id = %s ORDER BY id ASC",
                (user["id"],),
            )
        except Exception:  # noqa: BLE001 - no `steps` column before the v1.11 migration
            cur.connection.rollback()
            cur.execute(
                "SELECT id, role, content, citations, created_at, NULL FROM assistant_messages "
                "WHERE user_id = %s ORDER BY id ASC",
                (user["id"],),
            )
        rows = cur.fetchall()
    return {
        "items": [
            {"id": r[0], "role": r[1], "content": r[2], "citations": r[3] or [], "created_at": r[4],
             "trail": r[5]}
            for r in rows
        ]
    }


def _client_for(user: dict) -> OllamaClient:
    # Chat and its context-building embedding are the only Ollama work in this
    # app done on behalf of a named person, so they are the only calls
    # attributed to one. See the ollama_calls comment in db/init.sql.
    ollama = OllamaClient(
        **get_effective_ollama_config(),
        on_call=lambda **call: ollama_usage.record("api", user_id=user["id"], **call),
    )
    if not ollama.enabled:
        raise HTTPException(
            status_code=503,
            detail="The AI assistant is disabled — an admin can enable Ollama under Admin → Ollama Settings.",
        )
    return ollama


UNREACHABLE = ("Couldn't reach Ollama, or the configured model isn't available — check "
               "Admin → Ollama Settings and confirm the model has been pulled.")


def _semantic_for(ollama: OllamaClient):
    """search_case's fallback when no words match: the same embedding
    similarity the single search uses. None when no embed model is set."""
    if not ollama.embed_model:
        return None

    def semantic(query: str):
        vec = ollama.embed(query)
        if vec is None:
            return []
        out = []
        with db_cursor() as cur:
            for _, eid in _embedding_entities(cur, vec, 6):
                cur.execute("SELECT entity_type, name FROM entities WHERE id = %s", (eid,))
                row = cur.fetchone()
                if row:
                    out.append(("entity", eid, f"{row[0].capitalize()}: {row[1]}"))
            for _, rid in _embedding_reports(cur, vec, 4):
                cur.execute("SELECT title FROM reports WHERE id = %s", (rid,))
                row = cur.fetchone()
                if row:
                    out.append(("report", rid, f"Report: {row[0]}"))
        return out
    return semantic


def _save(user: dict, question: str, done: dict) -> dict:
    """Persist one finished turn. Nothing is written until there is a real
    answer, so a failed question never leaves an orphan in the history."""
    trail = {"steps": done["steps"], "thinking": done["thinking"], "seconds": done["seconds"],
             "lookups": done["lookups"], "mode": done["mode"], "notes": done.get("notes") or []}
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO assistant_messages (user_id, role, content) VALUES (%s, 'user', %s)",
            (user["id"], question),
        )
        try:
            cur.execute("SAVEPOINT trail")
            cur.execute(
                "INSERT INTO assistant_messages (user_id, role, content, citations, steps) "
                "VALUES (%s, 'assistant', %s, %s, %s) RETURNING id, created_at",
                (user["id"], done["answer"], json.dumps(done["citations"]), json.dumps(trail)),
            )
        except Exception:  # noqa: BLE001 - no `steps` column before the v1.11 migration
            cur.execute("ROLLBACK TO SAVEPOINT trail")
            cur.execute(
                "INSERT INTO assistant_messages (user_id, role, content, citations) "
                "VALUES (%s, 'assistant', %s, %s) RETURNING id, created_at",
                (user["id"], done["answer"], json.dumps(done["citations"])),
            )
        new_id, created_at = cur.fetchone()

    # The assistant reads case data on the user's behalf, so what it looked at
    # is an access event. Neither the question nor what it searched FOR is
    # copied here -- both are already in that user's own conversation, and
    # copying them into a log with different access rules would spread the
    # case data further, not audit it. Recorded: which lookups ran, every
    # record they returned (what the model read), and the ones the answer
    # cites.
    audit.record("assistant.query", user=user, object_type="assistant",
                 detail={"retrieved": (done.get("seen") or [])[:200],
                         "retrieved_count": len(done.get("seen") or []),
                         "cited": [c["id"] for c in done["citations"]],
                         "lookups": [s["tool"] for s in done["steps"]],
                         "mode": done["mode"]})
    return {"id": new_id, "role": "assistant", "content": done["answer"],
            "citations": done["citations"], "trail": trail,
            "created_at": created_at.isoformat() if created_at else None}


def _run(user: dict, question: str):
    """The agent for this user and question, as an event generator."""
    ollama = _client_for(user)
    settings = get_assistant_settings()
    with db_cursor() as cur:
        history = _load_history(cur, user["id"])

    def single_search(q):
        with db_cursor() as cur:
            return build_context(cur, ollama, q, user)

    return assistant_agent.run(ollama, question, history, settings, user,
                               semantic=_semantic_for(ollama), single_search=single_search)


@router.post("/ask")
def ask_streaming(payload: AssistantQuestion, user: dict = Depends(auth.require_user)):
    """The panel's endpoint. Streams newline-delimited JSON: one event per
    lookup as it runs, the model's reasoning when it thinks, and finally the
    saved answer — so an analyst watches the work happen rather than staring
    at "Thinking…" for a minute."""
    events = _run(user, payload.question)   # raises 503 here, before streaming, if disabled

    def stream():
        try:
            for event in events:
                if event["type"] == "done":
                    message = _save(user, payload.question, event)
                    yield json.dumps({"type": "answer", "message": message}, default=str) + "\n"
                    return
                if event["type"] == "error":
                    detail = UNREACHABLE if event["detail"] == "unreachable" else event["detail"]
                    yield json.dumps({"type": "error", "detail": detail}) + "\n"
                    return
                yield json.dumps(event, default=str) + "\n"
        except Exception:  # noqa: BLE001 - reported to the panel, logged in full here
            logger.exception("Assistant run failed")
            yield json.dumps({"type": "error",
                              "detail": "The assistant hit an error. The details are in the api log."}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/messages", status_code=201)
def ask_assistant(payload: AssistantQuestion, user: dict = Depends(auth.require_user)):
    """The same work as /ask, answered in one response. Kept for scripts and
    anything older than the streaming panel."""
    for event in _run(user, payload.question):
        if event["type"] == "done":
            return _save(user, payload.question, event)
        if event["type"] == "error":
            raise HTTPException(status_code=502,
                                detail=UNREACHABLE if event["detail"] == "unreachable" else event["detail"])
    raise HTTPException(status_code=502, detail=UNREACHABLE)


@router.delete("/messages")
def clear_messages(user: dict = Depends(auth.require_user)):
    """Clears the CALLING user's own conversation only -- this is a private
    research aid, not a shared case discussion log, so there's no admin
    override to clear someone else's history."""
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM assistant_messages WHERE user_id = %s", (user["id"],))
        deleted = cur.rowcount
    audit.record("assistant.clear", user=user, object_type="assistant",
                 detail={"messages_deleted": deleted})
    return {"status": "cleared"}
