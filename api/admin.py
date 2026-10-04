"""Admin-only account management: list users, change role or active state.

Kept separate from auth.py, which owns login/session/bootstrap — this is a
different concern (managing *other* people's accounts) and every endpoint
here is gated on auth.require_admin. Account creation itself still lives in
auth.py's POST /api/auth/register (already admin-gated once bootstrap is
done) — this module only adds what was missing: seeing who exists, and
changing an existing account's role or active state without creating a new
one, or setting a new password for someone who has forgotten theirs.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor

router = APIRouter(prefix="/api", tags=["admin"])

_USER_COLS = ["id", "username", "role", "is_active", "created_at", "failed_login_attempts", "locked_until"]


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=auth.MIN_PASSWORD_LENGTH, max_length=256)


def _row_to_user(row) -> dict:
    return dict(zip(_USER_COLS, row))


def _count_other_active_admins(cur, exclude_user_id: int) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE AND id != %s",
        (exclude_user_id,),
    )
    return cur.fetchone()[0]


@router.get("/users")
def list_users(user: dict = Depends(auth.require_admin)):
    with db_cursor() as cur:
        cur.execute(f"SELECT {', '.join(_USER_COLS)} FROM users ORDER BY username")
        rows = [_row_to_user(r) for r in cur.fetchall()]
    return {"items": rows}


@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, admin_user: dict = Depends(auth.require_admin)):
    if payload.role is not None and payload.role not in auth.VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {auth.VALID_ROLES}")

    with db_cursor(commit=True) as cur:
        cur.execute("SELECT role, is_active FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        current_role, current_is_active = row

        # Never let this be the action that leaves zero active admins —
        # that would lock everyone (including whoever just did this) out of
        # ever managing accounts again, with no way back in short of a
        # direct database edit. Only relevant if the target is CURRENTLY an
        # active admin and the change would take away one of those two
        # things.
        would_demote = payload.role is not None and payload.role != "admin"
        would_deactivate = payload.is_active is False
        if current_role == "admin" and current_is_active and (would_demote or would_deactivate):
            if _count_other_active_admins(cur, exclude_user_id=user_id) == 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Can't do that — this is the only active admin account. "
                        "Promote another user to admin first."
                    ),
                )

        updates = payload.model_dump(exclude_unset=True)
        if updates:
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            cur.execute(f"UPDATE users SET {set_clause} WHERE id = %s", [*updates.values(), user_id])

        cur.execute(f"SELECT {', '.join(_USER_COLS)} FROM users WHERE id = %s", (user_id,))
        updated = _row_to_user(cur.fetchone())

    # Values, not just field names, for this one: a change of role or of
    # active state IS the security-relevant fact, and neither is case data.
    audit.record(
        "user.update", user=admin_user, object_type="user",
        object_id=user_id, object_label=updated["username"],
        detail={"changes": updates} if updates else {"changes": {}},
    )
    return updated


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, payload: PasswordReset, request: Request,
                   admin_user: dict = Depends(auth.require_admin)):
    """Set a new password for an account.

    The alternative was deleting the analyst and recreating them, which
    orphans everything they authored from their name — created_by and
    author_id point at the old id. This keeps the account and its history.

    It also clears a lockout (the usual reason somebody is asking), and
    signs the account out everywhere: whoever was holding a session under
    the old password should not keep it. Resetting your OWN password keeps
    the session you are using, so an admin is not thrown out mid-task.
    """
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        username = row[0]
        cur.execute(
            "UPDATE users SET password_hash = %s, failed_login_attempts = 0, locked_until = NULL "
            "WHERE id = %s",
            (auth._hash_password(payload.password), user_id),
        )
        keep = request.cookies.get(auth.SESSION_COOKIE_NAME) if user_id == admin_user["id"] else None
        cur.execute("DELETE FROM sessions WHERE user_id = %s AND token IS DISTINCT FROM %s",
                    (user_id, keep))
        signed_out = cur.rowcount

    # The password itself never goes in the audit log, in any form.
    audit.record("user.password_reset", user=admin_user, object_type="user",
                 object_id=user_id, object_label=username,
                 detail={"sessions_ended": signed_out})
    return {"id": user_id, "username": username, "sessions_ended": signed_out}
