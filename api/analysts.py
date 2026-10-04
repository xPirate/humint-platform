"""Everything one analyst has put into the case file.

WHY THIS EXISTS

"What has Dana entered this month?" had no answer short of opening every
record and reading its byline. The authorship was always stored — entities
and relationships carry created_by, reports author_id, documents
uploaded_by, field reports the user their phone is enrolled to — it was just
never gathered in one place.

This is that place: one list, newest first, across every kind of thing a
person can author, with a count per kind so the page can say "41 entities,
12 reports" before anyone scrolls.

WHO CAN SEE IT

Any signed-in user, not only admins. Every record already shows who made it
to anyone who can open it; this collects what is already visible rather
than revealing anything new. The list of usernames is the same list any
report byline already shows.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import auth
from db import db_cursor

router = APIRouter(prefix="/api", tags=["analysts"])

KINDS = ("entity", "report", "relationship", "document", "field")

# One SELECT per kind, all shaped the same so they UNION:
#   kind, id (text), title, subtype, created_at, extra
# `extra` carries the one fact each kind needs beyond its title — an
# entity's archived state, a report's status, the far ends of a link.
_PARTS = {
    "entity": """
        SELECT 'entity', e.id, e.name, e.entity_type, e.created_at,
               CASE WHEN e.is_active THEN NULL ELSE 'archived' END
          FROM entities e
         WHERE e.created_by = %(uid)s AND e.merged_into IS NULL
    """,
    "report": """
        SELECT 'report', r.id, r.title, r.status, r.created_at, r.criticality
          FROM reports r
         WHERE r.author_id = %(uid)s
    """,
    "relationship": """
        SELECT 'relationship', rel.id::text,
               a.name || ' — ' || replace(rel.relationship_type, '_', ' ') || ' — ' || b.name,
               rel.confidence, rel.created_at,
               COALESCE(CASE WHEN rel.expires_on IS NOT NULL AND rel.expires_on < CURRENT_DATE
                             THEN 'expired' END, '') || '|' || a.id || '|' || b.id
          FROM relationships rel
          JOIN entities a ON a.id = rel.from_entity_id
          JOIN entities b ON b.id = rel.to_entity_id
         WHERE rel.created_by = %(uid)s
    """,
    "document": """
        SELECT 'document', d.id::text, COALESCE(d.title, d.filename), d.mime_type,
               d.uploaded_at,
               CASE WHEN d.report_id IS NOT NULL THEN 'report:' || d.report_id
                    WHEN d.entity_id IS NOT NULL THEN 'entity:' || d.entity_id END
          FROM attachments d
         WHERE d.uploaded_by = %(uid)s
    """,
    "field": """
        SELECT 'field', f.id::text, f.title, f.status, f.received_at,
               COALESCE(f.report_id, '') || '|' || COALESCE(f.device_label, '')
          FROM field_submissions f
         WHERE f.user_id = %(uid)s
    """,
}


def _user(cur, ident: str):
    """By id or by username, so a link can carry either."""
    if ident.isdigit():
        cur.execute("SELECT id, username, role, is_active, created_at FROM users WHERE id = %s",
                    (int(ident),))
    else:
        cur.execute("SELECT id, username, role, is_active, created_at FROM users "
                    "WHERE lower(username) = lower(%s)", (ident,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such analyst")
    return dict(zip(("id", "username", "role", "is_active", "created_at"), row))


@router.get("/analysts")
def list_analysts(q: Optional[str] = Query(default=None),
                  user: dict = Depends(auth.require_user)):
    """Every account, for the picker and for global search."""
    with db_cursor() as cur:
        params: list = []
        where = ""
        if q:
            where = "WHERE username ILIKE %s"
            params.append(f"%{q.strip()}%")
        cur.execute(f"SELECT id, username, role, is_active FROM users {where} "
                    "ORDER BY is_active DESC, lower(username) LIMIT 50", params)
        return {"items": [dict(zip(("id", "username", "role", "is_active"), r))
                          for r in cur.fetchall()]}


@router.get("/analysts/{ident}/activity")
def analyst_activity(
    ident: str,
    kind: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    since: Optional[date] = Query(default=None),
    until: Optional[date] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(auth.require_user),
):
    if kind is not None and kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(KINDS)}")
    with db_cursor() as cur:
        analyst = _user(cur, ident)
        params = {"uid": analyst["id"], "q": f"%{q.strip()}%" if q else None,
                  "since": since, "until": until, "limit": limit, "offset": offset}
        # The same filters apply to every kind, outside the UNION, so each
        # part stays a plain indexed lookup on its author column.
        def filtered(kinds):
            union = " UNION ALL ".join(_PARTS[k] for k in kinds)
            return f"""
                SELECT * FROM ({union}) AS a(kind, id, title, subtype, created_at, extra)
                 WHERE (%(q)s::text IS NULL OR a.title ILIKE %(q)s)
                   AND (%(since)s::date IS NULL OR a.created_at >= %(since)s::date)
                   AND (%(until)s::date IS NULL OR a.created_at < %(until)s::date + 1)
            """
        # Counts are across every kind whatever `kind` is set to: they label
        # the tabs, and a tab that reads 0 because another one is selected
        # would be wrong.
        cur.execute(f"SELECT kind, count(*) FROM ({filtered(KINDS)}) f GROUP BY kind", params)
        counts = {k: 0 for k in KINDS}
        counts.update(dict(cur.fetchall()))
        cur.execute(f"{filtered(KINDS if kind is None else (kind,))} "
                    "ORDER BY created_at DESC, kind, id LIMIT %(limit)s OFFSET %(offset)s",
                    params)
        items = []
        for k, item_id, title, subtype, created_at, extra in cur.fetchall():
            item = {"kind": k, "id": item_id, "title": title, "subtype": subtype,
                    "created_at": created_at}
            if k == "entity":
                item["archived"] = extra == "archived"
            elif k == "report":
                item["criticality"] = extra
            elif k == "relationship":
                expired, a_id, b_id = (extra or "||").split("|", 2)
                item.update(expired=expired == "expired", from_entity_id=a_id, to_entity_id=b_id)
            elif k == "document":
                if extra:
                    parent_kind, parent_id = extra.split(":", 1)
                    item["filed_on"] = {"kind": parent_kind, "id": parent_id}
            elif k == "field":
                report_id, device = (extra or "|").split("|", 1)
                item.update(report_id=report_id or None, device_label=device or None)
            items.append(item)

    total = sum(counts.values()) if kind is None else counts.get(kind, 0)
    return {"analyst": analyst, "counts": counts, "total": total,
            "items": items, "limit": limit, "offset": offset}
