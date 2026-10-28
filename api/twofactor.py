"""Two-factor sign-in: a six-digit code from an authenticator app (TOTP).

A password alone is one thing to steal. On the field server the console's
sign-in page is reachable by anyone who joins the hotspot, and at HQ by anyone
on the LAN; a code from a phone in the analyst's pocket is the second thing.

  * Each person turns it on for themselves (Account → Two-factor sign-in):
    scan a QR code, type one code to prove it works, and keep the ten
    single-use recovery codes they are shown once.
  * An admin can require it for everyone. Someone without it then signs in to
    a session that can do nothing except set it up.
  * An admin can reset someone's (a lost phone); that is audited.

RFC 6238 TOTP, SHA-1, six digits, 30-second steps — what every authenticator
app speaks. Implemented here with the standard library rather than a
dependency: it is twenty lines, and a field server installs nothing at runtime.
A code is accepted one step either side of now (clock drift between phone and
server), and never twice: the last step used is stored, so a code read over
someone's shoulder is worthless once they have signed in with it.

Recovery codes are stored only as SHA-256 hashes (they are random, 50 bits,
so a slow hash buys nothing) and each works once.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timezone
from typing import Optional

import segno
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor

router = APIRouter(prefix="/api/auth/2fa", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1                      # steps either side of now
RECOVERY_CODES = 10
ISSUER = "HUMINT"
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i


# ---- TOTP ------------------------------------------------------------------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(at: Optional[float] = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def matching_step(secret: str, code: str, last_step: Optional[int], at: Optional[float] = None) -> Optional[int]:
    """The step `code` is valid for (within the window), or None. Steps at or
    before last_step are refused: no code works twice."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = current_step(at)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, username: str, instance: str) -> str:
    from urllib.parse import quote
    label = quote(f"{instance}:{username}")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(instance)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


# ---- recovery codes ---------------------------------------------------------

def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()


def issue_recovery_codes(cur, user_id: int) -> list:
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODES)]
    cur.execute("DELETE FROM user_recovery_codes WHERE user_id = %s", (user_id,))
    for c in codes:
        cur.execute("INSERT INTO user_recovery_codes (user_id, code_hash) VALUES (%s, %s)",
                    (user_id, _hash_code(c)))
    return codes


def use_recovery_code(cur, user_id: int, code: str) -> bool:
    code = (code or "").strip().lower()
    if len(code.replace("-", "")) != 10:
        return False
    cur.execute("UPDATE user_recovery_codes SET used_at = now() "
                "WHERE user_id = %s AND code_hash = %s AND used_at IS NULL RETURNING id",
                (user_id, _hash_code(code)))
    return cur.fetchone() is not None


# ---- used by auth.login ------------------------------------------------------

def required_for_everyone(cur) -> bool:
    cur.execute("SELECT require_2fa FROM app_settings WHERE id = 1")
    row = cur.fetchone()
    return bool(row and row[0])


def check_second_factor(cur, user_id: int, otp: Optional[str], client_epoch: Optional[float]):
    """For a user whose password was right. Returns (ok, why) where why is
    'ok', 'recovery', 'missing', 'wrong' or 'clock' (the code is right for the
    device's clock but not this server's — the field server's clock is being
    set from that device and has not caught up yet)."""
    cur.execute("SELECT totp_secret, totp_last_step FROM users WHERE id = %s", (user_id,))
    secret, last = cur.fetchone()
    if not otp:
        return False, "missing"
    step = matching_step(secret, otp, last)
    if step is not None:
        cur.execute("UPDATE users SET totp_last_step = %s WHERE id = %s", (step, user_id))
        return True, "ok"
    if use_recovery_code(cur, user_id, otp):
        return True, "recovery"
    if client_epoch and matching_step(secret, otp, last, at=client_epoch) is not None:
        return False, "clock"
    return False, "wrong"


# ---- endpoints: your own -----------------------------------------------------

class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _instance_name() -> str:
    import os
    return os.environ.get("INSTANCE_NAME") or ISSUER


@router.get("")
def status(user: dict = Depends(auth.require_user_or_enrolling)):
    with db_cursor() as cur:
        cur.execute("SELECT totp_enabled_at FROM users WHERE id = %s", (user["id"],))
        enabled_at = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM user_recovery_codes WHERE user_id = %s AND used_at IS NULL",
                    (user["id"],))
        left = cur.fetchone()[0]
        required = required_for_everyone(cur)
    return {"enabled": enabled_at is not None, "enabled_at": enabled_at, "required": required,
            "recovery_codes_left": left if enabled_at else 0}


@router.post("/setup")
def setup(user: dict = Depends(auth.require_user_or_enrolling)):
    """Start (or restart) enrollment: a new secret, not active until a code
    from it has been typed back."""
    secret = new_secret()
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET totp_pending_secret = %s WHERE id = %s", (secret, user["id"]))
    uri = otpauth_uri(secret, user["username"], _instance_name())
    qr = segno.make(uri, error="m").svg_inline(scale=5, dark="#000", light="#fff", border=2)
    return {"secret": secret, "uri": uri, "qr_svg": qr}


@router.post("/enable")
def enable(payload: CodeIn, user: dict = Depends(auth.require_user_or_enrolling)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT totp_pending_secret FROM users WHERE id = %s", (user["id"],))
        secret = cur.fetchone()[0]
        step = matching_step(secret, payload.code, None) if secret else None
        if step is not None:
            cur.execute(
                "UPDATE users SET totp_secret = totp_pending_secret, totp_pending_secret = NULL, "
                "totp_enabled_at = now(), totp_last_step = %s WHERE id = %s", (step, user["id"]))
            codes = issue_recovery_codes(cur, user["id"])
            cur.execute("UPDATE sessions SET needs_2fa_setup = FALSE WHERE user_id = %s", (user["id"],))
    if not secret:
        raise HTTPException(status_code=400, detail="Start setup first")
    if step is None:
        raise HTTPException(status_code=400,
                            detail="That code does not match. Check the phone's time is right, and type the code "
                                   "showing now.")
    audit.record("auth.2fa_enabled", user=user, object_type="user", object_id=user["id"],
                 object_label=user["username"])
    return {"enabled": True, "recovery_codes": codes}


@router.post("/disable")
def disable(payload: PasswordIn, user: dict = Depends(auth.require_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
        ok = auth._verify_password(payload.password, cur.fetchone()[0])
        if ok:
            _clear(cur, user["id"])
    if not ok:
        raise HTTPException(status_code=403, detail="Password is not right")
    audit.record("auth.2fa_disabled", user=user, object_type="user", object_id=user["id"],
                 object_label=user["username"])
    return {"enabled": False}


@router.post("/recovery-codes")
def new_recovery_codes(payload: PasswordIn, user: dict = Depends(auth.require_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT password_hash, totp_enabled_at FROM users WHERE id = %s", (user["id"],))
        pw_hash, enabled = cur.fetchone()
        ok = auth._verify_password(payload.password, pw_hash) and enabled is not None
        codes = issue_recovery_codes(cur, user["id"]) if ok else None
    if not ok:
        raise HTTPException(status_code=403, detail="Password is not right, or two-factor is off")
    audit.record("auth.2fa_recovery_codes", user=user, object_type="user", object_id=user["id"],
                 object_label=user["username"])
    return {"recovery_codes": codes}


def _clear(cur, user_id: int):
    cur.execute("UPDATE users SET totp_secret = NULL, totp_pending_secret = NULL, totp_enabled_at = NULL, "
                "totp_last_step = NULL WHERE id = %s", (user_id,))
    cur.execute("DELETE FROM user_recovery_codes WHERE user_id = %s", (user_id,))


# ---- endpoints: admin ----------------------------------------------------------

class SecuritySettings(BaseModel):
    require_2fa: bool


@admin_router.get("/security-settings")
def get_security(user: dict = Depends(auth.require_admin)):
    with db_cursor() as cur:
        return {"require_2fa": required_for_everyone(cur)}


@admin_router.patch("/security-settings")
def set_security(payload: SecuritySettings, user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        cur.execute("UPDATE app_settings SET require_2fa = %s WHERE id = 1", (payload.require_2fa,))
        if payload.require_2fa:
            # Takes effect now, not at everyone's next sign-in: sessions of
            # people without it can do nothing until they set it up. Not the
            # admin's own, so they can finish what they are doing.
            cur.execute(
                "UPDATE sessions s SET needs_2fa_setup = TRUE FROM users u "
                "WHERE u.id = s.user_id AND u.totp_enabled_at IS NULL AND u.id <> %s", (user["id"],))
        cur.execute("SELECT totp_enabled_at FROM users WHERE id = %s", (user["id"],))
        self_enabled = cur.fetchone()[0] is not None
    audit.record("settings.require_2fa", user=user, object_type="settings", object_label="security",
                 detail={"require_2fa": payload.require_2fa})
    return {"require_2fa": payload.require_2fa,
            "note": None if self_enabled or not payload.require_2fa else
            "You have not set it up yourself yet: you will be asked to at your next sign-in."}


@admin_router.post("/users/{user_id}/2fa/reset")
def reset_for_user(user_id: int, user: dict = Depends(auth.require_admin)):
    """A lost phone. They sign in with the password alone next time (and are
    asked to set it up again if it is required)."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            _clear(cur, user_id)
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    audit.record("auth.2fa_reset", user=user, object_type="user", object_id=user_id, object_label=row[0])
    return {"reset": True, "at": datetime.now(timezone.utc).isoformat()}
