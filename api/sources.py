"""Source protection: a protected Source is known to the case file only by its
code name; who it really is lives apart, readable only by its handlers.

Why a separate table rather than hiding fields: the name on a record goes
everywhere — search, the network, the map, report mentions, PDF exports, field
packages, the assistant's context, audit labels. Filtering the true name out
of every one of those is a promise nobody could keep as the app grows. So
protecting a source MOVES the identity out: the record's name becomes the
code name, and the true name (and, by default, the description, which is
usually where a source's background was written) goes into source_identity, which only this module reads, and only for a handler. Every
read of it is in the audit log.

  * Anyone who can edit can protect a source; they become its first handler.
  * Handlers read and edit the identity, and add or remove handlers. An admin
    can manage the handler list too — including adding themselves, which is
    audited — but is not a handler by virtue of being an admin.
  * Files attached directly to a protected source (a photo, a scanned ID) are
    shown only to its handlers; see visible_attachment_sql().

What this cannot do, and the protect dialog says so: a report that names the
source in its prose, or a link to a Person record of the same individual,
still identifies them. Those are for the analyst to remove.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor

router = APIRouter(prefix="/api/sources", tags=["sources"])


# ---- used elsewhere ------------------------------------------------------------

def visible_attachment_sql(user_id: int, entity_col: str = "entity_id") -> str:
    """SQL condition: the attachment is not on a protected source, or the user
    handles that source. user_id is an int (cast here), never user input."""
    return ("NOT EXISTS (SELECT 1 FROM source_identity si_ WHERE si_.entity_id = " + entity_col +
            " AND NOT EXISTS (SELECT 1 FROM source_handlers sh_ WHERE sh_.entity_id = si_.entity_id"
            f" AND sh_.user_id = {int(user_id)}))")


def attachment_hidden(cur, attachment_id: int, user: dict) -> bool:
    cur.execute("SELECT 1 FROM attachments a WHERE a.id = %s AND NOT (" +
                visible_attachment_sql(user["id"], "a.entity_id") + ")", (attachment_id,))
    return cur.fetchone() is not None


def is_protected(cur, entity_id: str) -> bool:
    cur.execute("SELECT 1 FROM source_identity WHERE entity_id = %s", (entity_id,))
    return cur.fetchone() is not None


def _is_handler(cur, entity_id: str, user_id: int) -> bool:
    cur.execute("SELECT 1 FROM source_handlers WHERE entity_id = %s AND user_id = %s", (entity_id, user_id))
    return cur.fetchone() is not None


def _source_or_404(cur, entity_id: str):
    cur.execute("SELECT name, description, entity_type FROM entities WHERE id = %s", (entity_id,))
    row = cur.fetchone()
    if row is None or row[2] != "source":
        raise HTTPException(status_code=404, detail="Source not found")
    return row


def _handlers(cur, entity_id: str) -> list:
    cur.execute("SELECT u.id, u.username FROM source_handlers h JOIN users u ON u.id = h.user_id "
                "WHERE h.entity_id = %s ORDER BY u.username", (entity_id,))
    return [{"id": r[0], "username": r[1]} for r in cur.fetchall()]


def _require_handler(cur, entity_id: str, user: dict):
    if not is_protected(cur, entity_id):
        raise HTTPException(status_code=400, detail="This source is not protected")
    if not _is_handler(cur, entity_id, user["id"]):
        raise HTTPException(status_code=403, detail="Only this source's handlers can do that")


# ---- endpoints -------------------------------------------------------------------

@router.get("/{entity_id}/protection")
def protection(entity_id: str, user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        _source_or_404(cur, entity_id)
        protected = is_protected(cur, entity_id)
        handlers = _handlers(cur, entity_id) if protected else []
        cur.execute("SELECT count(*) FROM attachments WHERE entity_id = %s", (entity_id,))
        files = cur.fetchone()[0]
    you = any(h["id"] == user["id"] for h in handlers)
    return {"protected": protected, "handlers": handlers, "you_are_handler": you,
            "can_manage": you or user["role"] == "admin", "attachments": files}


class ProtectIn(BaseModel):
    code_name: str = Field(min_length=2, max_length=120)
    move_description: bool = True


@router.post("/{entity_id}/protect")
def protect(entity_id: str, payload: ProtectIn, user: dict = Depends(auth.require_user)):
    code = payload.code_name.strip()
    with db_cursor(commit=True) as cur:
        name, description, _ = _source_or_404(cur, entity_id)
        if is_protected(cur, entity_id):
            raise HTTPException(status_code=409, detail="Already protected")
        if code.casefold() == name.strip().casefold():
            raise HTTPException(status_code=400, detail="The code name must not be the source's name")
        notes = []
        if payload.move_description and description:
            notes.append(description.strip())
        cur.execute("INSERT INTO source_identity (entity_id, true_name, notes, protected_by, updated_by) "
                    "VALUES (%s, %s, %s, %s, %s)", (entity_id, name, "\n\n".join(notes) or None,
                                                    user["id"], user["id"]))
        cur.execute("INSERT INTO source_handlers (entity_id, user_id, added_by) VALUES (%s, %s, %s)",
                    (entity_id, user["id"], user["id"]))
        # The old text must not live on in the similarity index either.
        cur.execute("UPDATE entities SET name = %s, description = %s, embedding = NULL, updated_at = now() "
                    "WHERE id = %s", (code, None if payload.move_description else description, entity_id))
        # What still points at the person, for the analyst to deal with.
        cur.execute("SELECT count(*) FROM relationships WHERE from_entity_id = %s OR to_entity_id = %s",
                    (entity_id, entity_id))
        links = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM reports WHERE body_markdown ILIKE %s", (f"%{name}%",))
        reports_naming = cur.fetchone()[0]
    # The label is the code name: the audit log is read by admins, who are
    # not handlers by default.
    audit.record("source.protect", user=user, object_type="entity", object_id=entity_id, object_label=code,
                 detail={"moved_description": bool(payload.move_description and description)})
    return {"protected": True, "code_name": code, "relationships": links,
            "reports_naming_source": reports_naming}


@router.get("/{entity_id}/identity")
def get_identity(entity_id: str, user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        name = _source_or_404(cur, entity_id)[0]
        _require_handler(cur, entity_id, user)
        cur.execute("SELECT si.true_name, si.notes, si.protected_at, pu.username, si.updated_at, uu.username "
                    "FROM source_identity si LEFT JOIN users pu ON pu.id = si.protected_by "
                    "LEFT JOIN users uu ON uu.id = si.updated_by WHERE si.entity_id = %s", (entity_id,))
        r = cur.fetchone()
    audit.record("source.identity_viewed", user=user, object_type="entity", object_id=entity_id,
                 object_label=name)
    return {"true_name": r[0], "notes": r[1], "protected_at": r[2], "protected_by": r[3],
            "updated_at": r[4], "updated_by": r[5]}


class IdentityIn(BaseModel):
    true_name: str = Field(min_length=1, max_length=300)
    notes: Optional[str] = Field(default=None, max_length=20000)


@router.put("/{entity_id}/identity")
def put_identity(entity_id: str, payload: IdentityIn, user: dict = Depends(auth.require_user)):
    with db_cursor(commit=True) as cur:
        name = _source_or_404(cur, entity_id)[0]
        _require_handler(cur, entity_id, user)
        cur.execute("UPDATE source_identity SET true_name = %s, notes = %s, updated_at = now(), updated_by = %s "
                    "WHERE entity_id = %s", (payload.true_name.strip(), payload.notes, user["id"], entity_id))
    audit.record("source.identity_edited", user=user, object_type="entity", object_id=entity_id, object_label=name)
    return {"saved": True}


class HandlersIn(BaseModel):
    user_ids: List[int] = Field(min_length=1, max_length=50)


@router.put("/{entity_id}/handlers")
def put_handlers(entity_id: str, payload: HandlersIn, user: dict = Depends(auth.require_user)):
    want = sorted(set(payload.user_ids))
    with db_cursor(commit=True) as cur:
        name = _source_or_404(cur, entity_id)[0]
        if not is_protected(cur, entity_id):
            raise HTTPException(status_code=400, detail="This source is not protected")
        if not (_is_handler(cur, entity_id, user["id"]) or user["role"] == "admin"):
            raise HTTPException(status_code=403, detail="Only its handlers or an admin can change who handles it")
        cur.execute("SELECT id FROM users WHERE id = ANY(%s) AND is_active", (want,))
        if len(cur.fetchall()) != len(want):
            raise HTTPException(status_code=400, detail="Every handler must be an active account")
        before = [h["id"] for h in _handlers(cur, entity_id)]
        cur.execute("DELETE FROM source_handlers WHERE entity_id = %s AND NOT (user_id = ANY(%s))", (entity_id, want))
        for uid in want:
            cur.execute("INSERT INTO source_handlers (entity_id, user_id, added_by) VALUES (%s, %s, %s) "
                        "ON CONFLICT DO NOTHING", (entity_id, uid, user["id"]))
        after = _handlers(cur, entity_id)
    audit.record("source.handlers", user=user, object_type="entity", object_id=entity_id, object_label=name,
                 detail={"before": before, "after": [h["id"] for h in after]})
    return {"handlers": after}


@router.post("/{entity_id}/unprotect")
def unprotect(entity_id: str, user: dict = Depends(auth.require_user)):
    """Put the true name back on the record (and the notes in its
    description). Handlers only, and audited."""
    with db_cursor(commit=True) as cur:
        code, description, _ = _source_or_404(cur, entity_id)
        _require_handler(cur, entity_id, user)
        cur.execute("SELECT true_name, notes FROM source_identity WHERE entity_id = %s", (entity_id,))
        true_name, notes = cur.fetchone()
        merged = "\n\n".join(x for x in (description, notes) if x) or None
        cur.execute("UPDATE entities SET name = %s, description = %s, embedding = NULL, updated_at = now() "
                    "WHERE id = %s", (true_name, merged, entity_id))
        cur.execute("DELETE FROM source_handlers WHERE entity_id = %s", (entity_id,))
        cur.execute("DELETE FROM source_identity WHERE entity_id = %s", (entity_id,))
    audit.record("source.unprotect", user=user, object_type="entity", object_id=entity_id, object_label=code)
    return {"protected": False}
