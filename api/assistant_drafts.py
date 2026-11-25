"""The assistant's drafts: things it can prepare, that a person makes real.

Until v1.18 the assistant could only look things up. Asked to "write that up"
or "add a priority for it", the best it could do was print text to copy. Now
it can prepare the thing itself, as a DRAFT under its answer:

    draft_report        a report (made as a draft report, linked to the
                        records it is about)
    draft_priority      an intelligence priority (the question, indicators,
                        records)
    send_outside_event  an outside event to Documents
    propose_link        a link between two records — straight into the
                        Review queue, where every proposed link already goes

NOTHING IS WRITTEN UNTIL A PERSON SAYS SO. A draft is a row here, not a
report or a priority. The card under the answer shows what it would make;
Apply makes it through the same functions the console's own forms call (so
the same validation, the same audit entries, under the person's name), and
Discard drops it. A proposed link is the one exception in form only: the
Review queue is itself the approval step for links, so it goes there, and is
accepted or dismissed there like any other proposal.

The tools follow assistant_tools' rules: they never raise to the model, they
accept names where they ask for ids, and they answer in a line of text the
model can read back.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor

router = APIRouter(prefix="/api/assistant/drafts", tags=["assistant"])

MAX_DRAFTS = 5
KINDS = ("report", "priority", "outside_to_document", "link")
PRECEDENCE = {"flash": "Flash", "immediate": "Immediate", "priority": "Priority", "routine": "Routine"}


def _tools():
    import assistant_tools  # noqa: PLC0415 - assistant_tools imports this module at its end
    return assistant_tools


def _resolve_all(cur, refs) -> tuple[list, list]:
    """Ids for the records named; the names that matched nothing (or several)."""
    t = _tools()
    ids, missed = [], []
    for ref in (refs or [])[:20]:
        if not isinstance(ref, str) or not ref.strip():
            continue
        eid, _ = t.resolve_entity(cur, ref)
        if eid:
            if eid not in ids:
                ids.append(eid)
        else:
            missed.append(ref)
    return ids, missed


def _names(cur, ids) -> list:
    if not ids:
        return []
    cur.execute("SELECT id, name, entity_type FROM entities WHERE id = ANY(%s)", (list(ids),))
    by = {r[0]: {"id": r[0], "name": r[1], "entity_type": r[2]} for r in cur.fetchall()}
    return [by[i] for i in ids if i in by]


def _add(ctx, kind: str, payload: dict, summary: str, status: str = "pending", result=None) -> int | None:
    drafts = ctx.setdefault("drafts", [])
    if len(drafts) >= MAX_DRAFTS:
        return None
    user = ctx["user"]
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO assistant_drafts (user_id, kind, payload, summary, status, result, decided_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s = 'pending' THEN NULL ELSE now() END) RETURNING id",
                    (user["id"], kind, json.dumps(payload), summary[:300], status,
                     json.dumps(result) if result is not None else None, status))
        did = cur.fetchone()[0]
    drafts.append(did)
    return did


def _full(ctx) -> str:
    return (f"Not drafted: {MAX_DRAFTS} drafts is the most for one question. Say what else you would draft "
            f"in your answer instead.")


# ---- the tools ---------------------------------------------------------------------------------

def draft_report(ctx, title: str = "", body: str = "", about: list | None = None,
                 precedence: str | None = None) -> tuple[str, list]:
    title = " ".join((title or "").split())[:300]
    if not title or not (body or "").strip():
        return "draft_report needs a title and a body (the report's text, in Markdown).", []
    with db_cursor() as cur:
        ids, missed = _resolve_all(cur, about if isinstance(about, list) else [about] if about else [])
        linked = _names(cur, ids)
    prec = PRECEDENCE.get((precedence or "").strip().lower())
    did = _add(ctx, "report", {"title": title, "body_markdown": body.strip()[:20000], "entity_ids": ids,
                               "entities": linked, "criticality": prec},
               f"Report: {title}")
    if did is None:
        return _full(ctx), []
    t = _tools()
    note = f" Could not find: {', '.join(missed)}." if missed else ""
    return (f"Drafted the report '{title}' (draft #{did}), linked to {len(linked)} record(s).{note} "
            "It is shown under your answer; the analyst decides whether to make it. Tell them it is "
            "there; do not repeat the whole text."), [t._ent_ref(e["id"], e["entity_type"], e["name"]) for e in linked]


def draft_priority(ctx, title: str = "", question: str = "", indicators: list | None = None,
                   priority: int | None = 2, about: list | None = None) -> tuple[str, list]:
    title = " ".join((title or "").split())[:200]
    if not title:
        return "draft_priority needs a short title (and ideally the question to answer).", []
    try:
        pr = max(1, min(4, int(priority or 2)))
    except (TypeError, ValueError):
        pr = 2
    inds = [" ".join(str(i).split())[:200] for i in (indicators or []) if str(i).strip()][:12] \
        if isinstance(indicators, list) else ([str(indicators)] if indicators else [])
    with db_cursor() as cur:
        cur.execute("SELECT enabled FROM boards WHERE kind = 'priorities'")
        on = cur.fetchone()
        if not (on and on[0]):
            return ("The Priorities board is switched off here (an admin turns it on under Admin → Boards), so "
                    "no priority was drafted. Say so, and give the question in your answer instead."), []
        ids, missed = _resolve_all(cur, about if isinstance(about, list) else [about] if about else [])
        linked = _names(cur, ids)
    did = _add(ctx, "priority", {"title": title, "question": (question or "").strip()[:2000] or None,
                                 "indicators": inds, "priority": pr, "entity_ids": ids, "entities": linked},
               f"Priority {pr}: {title}")
    if did is None:
        return _full(ctx), []
    note = f" Could not find: {', '.join(missed)}." if missed else ""
    return (f"Drafted the priority '{title}' (P{pr}, draft #{did}) with {len(inds)} indicator(s).{note} The "
            "analyst decides whether to add it."), []


def send_outside_event(ctx, id: str = "", note: str | None = None) -> tuple[str, list]:  # noqa: A002
    t = _tools()
    eid = t._num_id(id, "outside")
    if eid is None:
        return "send_outside_event needs an outside event's id, e.g. outside-123.", []
    with db_cursor() as cur:
        try:
            cur.execute("SELECT id, title, triage_summary, status, dup_of FROM outside_events WHERE id = %s", (eid,))
            r = cur.fetchone()
        except Exception:  # noqa: BLE001
            cur.connection.rollback()
            r = None
    if not r:
        return f"No outside event outside-{eid}.", []
    if r[3] == "sent":
        return f"outside-{eid} is already in Documents.", []
    target = r[4] or r[0]
    label = r[2] or r[1]
    did = _add(ctx, "outside_to_document", {"event_id": target, "title": label,
                                            "source_note": (note or "").strip()[:300] or None},
               f"To Documents: {label}")
    if did is None:
        return _full(ctx), []
    return (f"Prepared sending '{label}' to Documents (draft #{did}); the analyst decides."), \
        [t._ref("outside_event", f"outside-{target}", f"Outside event: {t._clip(label, 60)}")]


def propose_link(ctx, from_id: str = "", to_id: str = "", relationship: str = "", reason: str = "") -> tuple[str, list]:
    t = _tools()
    rel = " ".join((relationship or "").split())[:80]
    if not (from_id and to_id and rel):
        return "propose_link needs from_id, to_id and the relationship (e.g. 'works for', 'drives').", []
    if len(ctx.setdefault("drafts", [])) >= MAX_DRAFTS:
        return _full(ctx), []
    with db_cursor(commit=True) as cur:
        a, ca = t.resolve_entity(cur, from_id)
        b, cb = t.resolve_entity(cur, to_id)
        if not a:
            return t._not_found(from_id, ca)
        if not b:
            return t._not_found(to_id, cb)
        if a == b:
            return "A record cannot be linked to itself.", []
        names = {e["id"]: e for e in _names(cur, [a, b])}
        cur.execute("SELECT 1 FROM relationships WHERE ((from_entity_id = %s AND to_entity_id = %s) OR "
                    "(from_entity_id = %s AND to_entity_id = %s)) LIMIT 1", (a, b, b, a))
        if cur.fetchone():
            return f"{names[a]['name']} and {names[b]['name']} are already linked; nothing proposed.", []
        evidence = {"signal": "assistant", "rule": "proposed by the assistant in a conversation",
                    "reason": (reason or "").strip()[:500], "suggested_type": rel, "signals": ["assistant"]}
        cur.execute(
            "INSERT INTO extraction_suggestions (source, suggestion_type, suggested_relationship_type, "
            " suggested_from_entity_id, suggested_to_entity_id, suggested_from_name, suggested_to_name, "
            " confidence, evidence) VALUES ('assistant', 'relationship', %s, %s, %s, %s, %s, NULL, %s::jsonb) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (rel, a, b, names[a]["name"], names[b]["name"], json.dumps(evidence)))
        row = cur.fetchone()
    if not row:
        return f"A link between {names[a]['name']} and {names[b]['name']} is already waiting in Review.", []
    _add(ctx, "link", {"from": names[a], "to": names[b], "relationship": rel, "reason": evidence["reason"]},
         f"Link: {names[a]['name']} — {rel} — {names[b]['name']}", status="queued",
         result={"suggestion_id": row[0]})
    audit.record("suggestion.propose", user=ctx["user"], object_type="suggestion", object_id=row[0],
                 object_label=f"{names[a]['name']} — {rel} — {names[b]['name']}",
                 detail={"via": "assistant conversation"})
    return (f"Proposed '{names[a]['name']} {rel} {names[b]['name']}' — it is in the Review queue for the "
            "analyst to accept or dismiss."), [t._ent_ref(a, names[a]["entity_type"], names[a]["name"]),
                                               t._ent_ref(b, names[b]["entity_type"], names[b]["name"])]


def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


TOOLS = [
    _fn("draft_report",
        "Prepare a report for the analyst to approve — only when they ask you to write something up or "
        "draft a report. Write the body in plain Markdown from what the lookups showed; it becomes a draft "
        "report linked to the records it is about once the analyst approves.",
        {"title": {"type": "string"},
         "body": {"type": "string", "description": "The report's text, Markdown"},
         "about": {"type": "array", "items": {"type": "string"}, "description": "Ids of the records it is about"},
         "precedence": {"type": "string", "description": "Optional: Routine, Priority, Immediate or Flash"}},
        ["title", "body"]),
    _fn("draft_priority",
        "Prepare an intelligence priority (a question the team needs answered) for the analyst to approve — "
        "only when they ask for one.",
        {"title": {"type": "string", "description": "Short name"},
         "question": {"type": "string", "description": "The question, written out"},
         "indicators": {"type": "array", "items": {"type": "string"},
                        "description": "Concrete things that would answer it"},
         "priority": {"type": "integer", "description": "1 (highest) to 4, default 2"},
         "about": {"type": "array", "items": {"type": "string"}, "description": "Ids of related records"}},
        ["title"]),
    _fn("send_outside_event",
        "Prepare sending an outside event (outside-<n>) to Documents, for the analyst to approve — only "
        "when they ask.",
        {"id": {"type": "string"}, "note": {"type": "string", "description": "Optional: where it came from"}},
        ["id"]),
    _fn("propose_link",
        "Propose a link between two records into the Review queue — only when the analyst asks you to link "
        "or connect records. Give the relationship in a few words ('works for', 'drives', 'lives at').",
        {"from_id": {"type": "string"}, "to_id": {"type": "string"},
         "relationship": {"type": "string"}, "reason": {"type": "string", "description": "What shows it"}},
        ["from_id", "to_id", "relationship"]),
]
TOOL_FUNCS = {"draft_report": draft_report, "draft_priority": draft_priority,
              "send_outside_event": send_outside_event, "propose_link": propose_link}


def describe(name: str, args: dict) -> str:
    a = args or {}
    return {"draft_report": f"Drafted a report “{a.get('title', '')}”",
            "draft_priority": f"Drafted a priority “{a.get('title', '')}”",
            "send_outside_event": f"Prepared sending {a.get('id', '')} to Documents",
            "propose_link": f"Proposed a link: {a.get('from_id', '')} — {a.get('relationship', '')} — {a.get('to_id', '')}"
            }.get(name, name)


# ---- the console's side ------------------------------------------------------------------------

def _row(r) -> dict:
    return {"id": r[0], "message_id": r[1], "kind": r[2], "payload": r[3], "summary": r[4], "status": r[5],
            "result": r[6], "created_at": r[7].isoformat() if r[7] else None,
            "decided_at": r[8].isoformat() if r[8] else None}


COLS = "id, message_id, kind, payload, summary, status, result, created_at, decided_at"


def for_messages(cur, message_ids: list) -> dict:
    """{message id: [drafts]} for the conversation view."""
    if not message_ids:
        return {}
    try:
        cur.execute(f"SELECT {COLS} FROM assistant_drafts WHERE message_id = ANY(%s) ORDER BY id", (message_ids,))
    except Exception:  # noqa: BLE001 - before the v1.18 migration
        cur.connection.rollback()
        return {}
    out: dict = {}
    for r in cur.fetchall():
        out.setdefault(r[1], []).append(_row(r))
    return out


def attach(cur, draft_ids: list, message_id: int, user_id: int) -> list:
    if not draft_ids:
        return []
    cur.execute(f"UPDATE assistant_drafts SET message_id = %s WHERE id = ANY(%s) AND user_id = %s RETURNING {COLS}",
                (message_id, draft_ids, user_id))
    return sorted((_row(r) for r in cur.fetchall()), key=lambda d: d["id"])


def _get(cur, draft_id: int, user: dict) -> dict:
    cur.execute(f"SELECT {COLS}, user_id FROM assistant_drafts WHERE id = %s", (draft_id,))
    r = cur.fetchone()
    if not r or r[9] != user["id"]:
        raise HTTPException(status_code=404, detail="No such draft.")
    return _row(r)


class ApplyRequest(BaseModel):
    # Optional changes before it is made: a report's title and text, a
    # priority's title and question.
    title: Optional[str] = Field(default=None, max_length=300)
    body_markdown: Optional[str] = Field(default=None, max_length=50000)
    question: Optional[str] = Field(default=None, max_length=2000)


@router.post("/{draft_id}/apply")
def apply(draft_id: int, payload: ApplyRequest = ApplyRequest(), user: dict = Depends(auth.require_user)):
    """Make it: through the console's own create functions, as this person."""
    with db_cursor() as cur:
        d = _get(cur, draft_id, user)
    if d["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"That draft is already {d['status']}.")
    p = d["payload"] or {}
    if d["kind"] == "report":
        import reports as reports_module  # noqa: PLC0415
        created = reports_module.create_report(reports_module.ReportCreate(
            title=(payload.title or p["title"]).strip(), body_markdown=payload.body_markdown or p["body_markdown"],
            status="draft", criticality=p.get("criticality"), entity_ids=p.get("entity_ids") or []), user)
        result = {"report_id": created["id"], "title": created["title"]}
    elif d["kind"] == "priority":
        import boards as boards_module  # noqa: PLC0415
        created = boards_module.create_priority(boards_module.PriorityWrite(
            title=(payload.title or p["title"]).strip(), question=payload.question or p.get("question"),
            priority=p.get("priority") or 2, indicators=p.get("indicators") or [],
            entity_ids=p.get("entity_ids") or []), user)
        result = {"priority_id": created["id"]}
    elif d["kind"] == "outside_to_document":
        import outside_events  # noqa: PLC0415
        created = outside_events.send_to_documents(
            int(p["event_id"]), outside_events.SendRequest(fetch_article=True, source_note=p.get("source_note")), user)
        result = {"document_id": created["document_id"], "title": created.get("title")}
    else:
        raise HTTPException(status_code=409, detail="That draft is not something to apply.")
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE assistant_drafts SET status = 'applied', result = %s, decided_at = now() WHERE id = %s",
                    (json.dumps(result), draft_id))
    audit.record("assistant.draft_apply", user=user, object_type="assistant_draft", object_id=draft_id,
                 object_label=d["summary"], detail={"kind": d["kind"], **result})
    with db_cursor() as cur:
        return _get(cur, draft_id, user)


@router.post("/{draft_id}/discard")
def discard(draft_id: int, user: dict = Depends(auth.require_user)):
    with db_cursor(commit=True) as cur:
        d = _get(cur, draft_id, user)
        if d["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"That draft is already {d['status']}.")
        cur.execute("UPDATE assistant_drafts SET status = 'discarded', decided_at = now() WHERE id = %s", (draft_id,))
        return _get(cur, draft_id, user)
