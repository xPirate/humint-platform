"""Analyst profiles: who the team are, and how to reach them.

WHY THIS EXISTS

Until now an account was a username, a role and a password. Anything else —
a callsign, a radio channel, a mobile number, whether someone is safe — had
nowhere to go except as an Entity, which puts a team member into the case
file next to the people the team is looking at: in search, on the network,
in exports. A profile keeps them out of it.

WHO CAN DO WHAT

  read    every signed-in user. This is the team directory; an analyst who
          cannot see how to reach a colleague has no use for it.
  edit    the analyst themselves, or any admin.

STATUS

The team's welfare state for the person: At liberty, Under duress,
Incapacitated, Deceased, Captured. Every change is stamped with who made it
and when, and written to the audit log with the old and new values — on a
team that uses it, a change of status is an event somebody acts on, and
"who said so, and when" is the first question.

CONTACTS

A free list, not a form. A radio operator has email, a radio channel, a
Meshtastic node, a MeshCore address and a phone; another analyst has a mobile
and one social account. Each entry is a kind, a value and an optional note;
the kind is free text and the console only suggests the common ones.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg2.extras import Json

import audit
import auth
from db import db_cursor

router = APIRouter(prefix="/api", tags=["profiles"])

STATUSES = ("At liberty", "Under duress", "Incapacitated", "Deceased", "Captured")
MAX_CONTACTS = 40

# What the console offers in the kind box. Suggestions only — anything typed
# is kept as typed.
SUGGESTED_KINDS = ["Mobile", "Phone", "Email", "Radio", "Meshtastic", "MeshCore",
                   "Signal", "Telegram", "WhatsApp", "Matrix", "Social", "Website", "Other"]

_FIELDS = ("display_name", "callsign", "role_title", "status", "status_note",
           "status_changed_at", "contacts", "notes", "updated_at")


class Contact(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=300)
    note: Optional[str] = Field(default=None, max_length=300)


class ProfileWrite(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    callsign: Optional[str] = Field(default=None, max_length=60)
    role_title: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = None
    status_note: Optional[str] = Field(default=None, max_length=500)
    contacts: Optional[list[Contact]] = Field(default=None, max_length=MAX_CONTACTS)
    notes: Optional[str] = Field(default=None, max_length=4000)


def _resolve(cur, ident: str) -> dict:
    if ident.isdigit():
        cur.execute("SELECT id, username, role, is_active FROM users WHERE id = %s", (int(ident),))
    else:
        cur.execute("SELECT id, username, role, is_active FROM users WHERE lower(username) = lower(%s)",
                    (ident,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such analyst")
    return dict(zip(("id", "username", "role", "is_active"), row))


def _profile(cur, user: dict) -> dict:
    cur.execute(
        f"SELECT {', '.join('p.' + f for f in _FIELDS)}, u.username "
        "  FROM user_profiles p LEFT JOIN users u ON u.id = p.status_changed_by "
        " WHERE p.user_id = %s", (user["id"],))
    row = cur.fetchone()
    out = {"user_id": user["id"], "username": user["username"], "role": user["role"],
           "is_active": user["is_active"]}
    if row is None:
        out.update({f: None for f in _FIELDS})
        out.update(status="At liberty", contacts=[], status_changed_by=None)
    else:
        out.update(dict(zip(_FIELDS, row[:len(_FIELDS)])))
        out["status_changed_by"] = row[len(_FIELDS)]
    return out


def _can_edit(actor: dict, target: dict) -> bool:
    return actor["role"] == "admin" or actor["id"] == target["id"]


@router.get("/profiles")
def list_profiles(user: dict = Depends(auth.require_user)):
    """The team directory: every account and its profile, active first."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT u.id, u.username, u.role, u.is_active, p.display_name, p.callsign, p.role_title, "
            "       COALESCE(p.status, 'At liberty'), p.status_note, p.status_changed_at, "
            "       COALESCE(p.contacts, '[]'::jsonb) "
            "  FROM users u LEFT JOIN user_profiles p ON p.user_id = u.id "
            " ORDER BY u.is_active DESC, lower(COALESCE(p.display_name, u.username))")
        keys = ("user_id", "username", "role", "is_active", "display_name", "callsign", "role_title",
                "status", "status_note", "status_changed_at", "contacts")
        items = [dict(zip(keys, r)) for r in cur.fetchall()]
    return {"items": items, "statuses": list(STATUSES), "suggested_kinds": SUGGESTED_KINDS}


@router.get("/profiles/{ident}")
def get_profile(ident: str, user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        target = _resolve(cur, ident)
        profile = _profile(cur, target)
    profile["can_edit"] = _can_edit(user, target)
    profile["statuses"] = list(STATUSES)
    profile["suggested_kinds"] = SUGGESTED_KINDS
    return profile


@router.put("/profiles/{ident}")
def put_profile(ident: str, payload: ProfileWrite, user: dict = Depends(auth.require_user)):
    """Replace the profile with what was sent. Fields left out are kept."""
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(STATUSES)}")
    if "status" in updates and updates["status"] is None:
        raise HTTPException(status_code=400, detail="status cannot be empty")
    for key in ("display_name", "callsign", "role_title", "status_note", "notes"):
        if key in updates and isinstance(updates[key], str):
            updates[key] = updates[key].strip() or None
    if "contacts" in updates:
        updates["contacts"] = [
            {"kind": c["kind"].strip(), "value": c["value"].strip(),
             **({"note": c["note"].strip()} if (c.get("note") or "").strip() else {})}
            for c in (updates["contacts"] or []) if c["kind"].strip() and c["value"].strip()
        ]

    with db_cursor(commit=True) as cur:
        target = _resolve(cur, ident)
        if not _can_edit(user, target):
            raise HTTPException(status_code=403, detail="Only this analyst or an admin can change this profile.")
        before = _profile(cur, target)
        cur.execute("INSERT INTO user_profiles (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (target["id"],))
        status_changed = "status" in updates and updates["status"] != before["status"]
        sets, values = [], []
        for key, value in updates.items():
            sets.append(f"{key} = %s")
            values.append(Json(value) if key == "contacts" else value)
        if status_changed:
            sets += ["status_changed_at = now()", "status_changed_by = %s"]
            values.append(user["id"])
        sets += ["updated_at = now()", "updated_by = %s"]
        values.append(user["id"])
        cur.execute(f"UPDATE user_profiles SET {', '.join(sets)} WHERE user_id = %s",
                    [*values, target["id"]])
        after = _profile(cur, target)

    # Field names only, as for every other edit — a profile's contact list is
    # the analyst's own and does not belong in a log everyone with audit
    # access can read. The status is the exception: its values ARE the event.
    audit.record("profile.update", user=user, object_type="user", object_id=target["id"],
                 object_label=target["username"], detail={"fields": sorted(updates)})
    if status_changed:
        audit.record("profile.status", user=user, object_type="user", object_id=target["id"],
                     object_label=target["username"],
                     detail={"from": before["status"], "to": updates["status"],
                             "note": updates.get("status_note", before.get("status_note"))})
    after["can_edit"] = True
    return after
