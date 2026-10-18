"""The field server's touch panel, asking the console for phone upload codes.

The phone app stores no credentials: it scans a code when it uploads and
forgets it (see field.py's reissue endpoint). So the natural place to get a
code in the field is the box itself — walk up, Menu → Phone upload, pick the
person, scan. This is the panel's only way into the console, and it can do
only that: list who can upload and from which phones, and issue a code.

How the panel proves it is the panel: a random token in a file only root and
the console can read (made by the API unit, PANEL_TOKEN_FILE), sent in a
header — and the request must come from the box itself. The panel runs as
root on the box; nothing on the network can read the file.

Anyone standing at an unlocked box can therefore issue a code. That is the
same trust the panel already has (it can lock, wipe and power off the box),
and what a code allows is narrow: posting field reports as that person,
which land in the review inbox rather than in the case file. Every code is
audited as issued by the touch panel, and an admin can switch this off
(Admin → Field devices). Read-only accounts are not offered: a code would let
them write.

On the Docker deployment PANEL_TOKEN_FILE is unset and all of this is 404.
"""
import hmac
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor
from field import _hash_token

router = APIRouter(prefix="/api/panel", tags=["panel"])
admin_router = APIRouter(prefix="/api/admin/panel-settings", tags=["admin"])

TOKEN_FILE = os.environ.get("PANEL_TOKEN_FILE", "")
PANEL = "touch panel"


def _enabled(cur) -> bool:
    cur.execute("SELECT panel_upload_codes FROM app_settings WHERE id = 1")
    row = cur.fetchone()
    return True if row is None or row[0] is None else bool(row[0])


def require_panel(request: Request, x_panel_token: Optional[str] = Header(default=None)):
    if not TOKEN_FILE:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        expected = open(TOKEN_FILE).read().strip()
    except OSError:
        raise HTTPException(status_code=503, detail="The panel token is missing")
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1") or not x_panel_token or not expected or \
            not hmac.compare_digest(x_panel_token.strip(), expected):
        raise HTTPException(status_code=403, detail="Not the panel")
    with db_cursor() as cur:
        if not _enabled(cur):
            raise HTTPException(status_code=403, detail="Phone codes from the panel are switched off "
                                                        "(Admin → Field devices)")


@router.get("/upload/people", dependencies=[Depends(require_panel)])
def people():
    """Everyone who can upload, with their phones."""
    with db_cursor() as cur:
        cur.execute("SELECT id, username FROM users WHERE is_active AND role <> 'viewer' "
                    "ORDER BY lower(username)")
        users = [{"id": r[0], "username": r[1], "devices": []} for r in cur.fetchall()]
        by_id = {u["id"]: u for u in users}
        cur.execute("SELECT id, user_id, label, last_seen_at FROM field_devices "
                    "WHERE revoked_at IS NULL ORDER BY label")
        for did, uid, label, seen in cur.fetchall():
            if uid in by_id:
                by_id[uid]["devices"].append({"id": did, "label": label,
                                              "last_seen_at": seen.isoformat() if seen else None})
    return {"items": users}


class CodeIn(BaseModel):
    # An existing phone, or a new one for this person.
    device_id: Optional[int] = None
    user_id: Optional[int] = None
    # Where the phone should send its reports: the address the panel shows.
    base_url: Optional[str] = Field(default=None, max_length=300)


@router.post("/upload/code", dependencies=[Depends(require_panel)])
def code(payload: CodeIn):
    token = secrets.token_urlsafe(32)
    base_url = (payload.base_url or "").strip() or None
    with db_cursor(commit=True) as cur:
        if payload.device_id is not None:
            cur.execute("SELECT d.label, d.revoked_at, d.base_url, u.username, u.is_active, u.role "
                        "FROM field_devices d JOIN users u ON u.id = d.user_id WHERE d.id = %s",
                        (payload.device_id,))
            row = cur.fetchone()
            if row is None or row[1] is not None:
                raise HTTPException(status_code=404, detail="No such phone")
            label, _, stored_url, username, active, role = row
            if not active or role == "viewer":
                raise HTTPException(status_code=400, detail=f"{username} cannot upload")
            base_url = base_url or stored_url
            cur.execute("UPDATE field_devices SET token_hash = %s, token_prefix = %s, base_url = %s "
                        "WHERE id = %s", (_hash_token(token), token[:6], base_url, payload.device_id))
            device_id, action = payload.device_id, "field.device.reissue"
        elif payload.user_id is not None:
            cur.execute("SELECT username, is_active, role FROM users WHERE id = %s", (payload.user_id,))
            row = cur.fetchone()
            if row is None or not row[1] or row[2] == "viewer":
                raise HTTPException(status_code=400, detail="That account cannot upload")
            username = row[0]
            label = f"{username}'s phone (from the panel)"
            cur.execute("INSERT INTO field_devices (label, user_id, token_hash, token_prefix, base_url) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (label, payload.user_id, _hash_token(token), token[:6], base_url))
            device_id, action = cur.fetchone()[0], "field.device.enroll"
        else:
            raise HTTPException(status_code=400, detail="device_id or user_id")
    audit.record(action, actor_username=PANEL, actor_kind="panel", object_type="field_device",
                 object_id=device_id, object_label=label,
                 detail={"for_user": username, "issued_at": "the field server's touch panel"})
    enrollment = {"v": 1, "url": base_url, "token": token, "label": label, "user": username}
    return {"device_id": device_id, "label": label, "username": username, "enrollment": enrollment}


# ---- admin switch -------------------------------------------------------------

class PanelSettings(BaseModel):
    panel_upload_codes: bool


@admin_router.get("")
def get_settings(user: dict = Depends(auth.require_admin)):
    with db_cursor() as cur:
        return {"available": bool(TOKEN_FILE), "panel_upload_codes": _enabled(cur)}


@admin_router.patch("")
def set_settings(payload: PanelSettings, user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        cur.execute("UPDATE app_settings SET panel_upload_codes = %s WHERE id = 1", (payload.panel_upload_codes,))
    audit.record("settings.panel_upload_codes", user=user, object_type="settings", object_label="touch panel",
                 detail={"panel_upload_codes": payload.panel_upload_codes})
    return {"panel_upload_codes": payload.panel_upload_codes}
