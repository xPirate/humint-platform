"""Team relays: a tablet that carries a team's reports home.

WHAT A RELAY IS

A team on a deployment — several days covering an event, a hotel room for a
base — takes one tablet running the Field app in relay mode. Each night the
team's phones send to the tablet over its own hotspot, exactly as they would
send to this console. The tablet holds the reports, encrypted, and when the
lead presses Sync over the VPN or back on the office network, it hands them
over here. Each report lands in the From the field queue under the phone and
analyst that wrote it, with a note that it came through the relay.

THE KEY AND ITS KEEP-ALIVE

A relay has its own credential, like a field device: write-only, hashed here,
revocable. Unlike a phone, the tablet has to keep it — it must reach home days
later with nobody scanning a code — so it is given a keep-alive. Every
check-in (every Sync) pushes the expiry out by `keepalive_days`; a relay that
goes quiet for longer than that loses its key on its own. A seized tablet
therefore cannot reach this console after a few days even if nobody noticed
it was gone. Expiry stops the relay sending; it never deletes anything on the
tablet. The way back is re-provisioning in person at the office.

PROVING WHO IS ANSWERING

The tablet finds this console by trying the addresses it was given, often over
a hotel network. Before it sends a report or its token it asks /api/relay/hello
to sign a random challenge with this console's key, and checks the signature
against the public key it was provisioned with. Something else answering at
the right address gets nothing.

Nothing reachable with a relay token returns case data, same as a device
token. Provisioning returns the team's names and ids — so the lead can say
whose phone is whose — and nothing else from the file.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

import audit
import auth
import field as field_module
import field_templates as templates
from db import db_cursor

logger = logging.getLogger(__name__)

tablet = APIRouter(prefix="/api/relay", tags=["relay"])
manage = APIRouter(prefix="/api/field/relays", tags=["relay-management"])

PROVISION_MINUTES = 30
DEFAULT_KEEPALIVE = 3
MAX_KEEPALIVE = 14
HELLO_PREFIX = b"humint-relay-hello:v1:"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# The console's own key
# ---------------------------------------------------------------------------

def _identity() -> ec.EllipticCurvePrivateKey:
    """This console's signing key, made the first time anything asks.

    Kept in the database, so a backup and restore keeps it — a restored
    console is still the console its relays were provisioned against.
    """
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT private_key_pem FROM console_identity WHERE id = 1")
        row = cur.fetchone()
        if row:
            return serialization.load_pem_private_key(row[0].encode(), password=None)
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        cur.execute("INSERT INTO console_identity (id, private_key_pem) VALUES (1, %s) "
                    "ON CONFLICT (id) DO NOTHING", (pem,))
        cur.execute("SELECT private_key_pem FROM console_identity WHERE id = 1")
        return serialization.load_pem_private_key(cur.fetchone()[0].encode(), password=None)


def _public_der(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


def console_fingerprint(key: ec.EllipticCurvePrivateKey | None = None) -> str:
    """Short, readable: what an admin and a lead can compare by eye."""
    der = _public_der(key or _identity())
    h = hashlib.sha256(der).hexdigest().upper()
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def sweep_expired(cur) -> list:
    """Drop the key of every relay past its keep-alive. Returns those it
    dropped, so the caller can audit them."""
    cur.execute(
        "UPDATE field_relays SET revoked_at = now(), revoke_reason = 'expired' "
        " WHERE revoked_at IS NULL AND token_hash IS NOT NULL AND expires_at < now() "
        "RETURNING id, label")
    return cur.fetchall()


def _audit_expired(rows):
    for rid, label in rows:
        audit.record("field.relay.expire", actor_kind="system", object_type="field_relay",
                     object_id=rid, object_label=label,
                     detail={"note": "no check-in within the keep-alive; key dropped"})


# ---------------------------------------------------------------------------
# Relay authentication
# ---------------------------------------------------------------------------

def require_relay(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="A relay token is required.")
    token = authorization[7:].strip()
    with db_cursor(commit=True) as cur:
        expired = sweep_expired(cur)
        cur.execute(
            "SELECT id, label, token_hash, revoked_at, revoke_reason, keepalive_days, created_by "
            "  FROM field_relays WHERE token_hash = %s", (_hash(token),))
        row = cur.fetchone()
    _audit_expired(expired)
    if row is None or not hmac.compare_digest(row[2], _hash(token)):
        raise HTTPException(status_code=401, detail="That relay token is not valid.")
    rid, label, _, revoked_at, reason, keepalive, created_by = row
    if revoked_at is not None:
        # Worded for the lead holding the tablet, who needs to know what to
        # do next. Only someone who once held a valid token sees this.
        if reason == "expired":
            raise HTTPException(
                status_code=401,
                detail="This relay's key expired: it did not check in within its keep-alive. "
                       "Its reports are still on the tablet. Re-provision it at the office to send them.")
        raise HTTPException(status_code=401,
                            detail="This relay has been revoked. Its reports are still on the tablet; "
                                   "re-provision it at the office to send them.")
    return {"id": rid, "label": label, "keepalive_days": keepalive, "created_by": created_by,
            "ip": request.client.host if request.client else None}


# ---------------------------------------------------------------------------
# Tablet-facing
# ---------------------------------------------------------------------------

class HelloRequest(BaseModel):
    nonce: str = Field(min_length=8, max_length=200)


@tablet.post("/hello")
def hello(payload: HelloRequest):
    """Sign the tablet's challenge. No token: the point is for the tablet to
    check who it is talking to *before* it sends one."""
    try:
        nonce = base64.b64decode(payload.nonce, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="The challenge must be base64.")
    if not 16 <= len(nonce) <= 64:
        raise HTTPException(status_code=400, detail="The challenge must be 16 to 64 bytes.")
    key = _identity()
    sig = key.sign(HELLO_PREFIX + nonce, ec.ECDSA(hashes.SHA256()))
    return {"console": "humint-platform", "fingerprint": console_fingerprint(key),
            "public_key": base64.b64encode(_public_der(key)).decode(),
            "signature": base64.b64encode(sig).decode(),
            "server_time": datetime.now(timezone.utc).isoformat()}


class ProvisionRequest(BaseModel):
    code: str = Field(min_length=8, max_length=200)


@tablet.post("/provision")
def provision(payload: ProvisionRequest, request: Request):
    """Swap a one-time code for the relay's token and its bundle."""
    token = secrets.token_urlsafe(32)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, label, keepalive_days, addresses, provision_expires_at "
            "  FROM field_relays WHERE provision_hash = %s", (_hash(payload.code.strip()),))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="That provisioning code is not valid.")
        rid, label, keepalive, addresses, until = row
        if until is None or until < datetime.now(timezone.utc):
            raise HTTPException(status_code=401,
                                detail="That provisioning code has expired. Show a new one on the console.")
        cur.execute(
            "UPDATE field_relays SET token_hash = %s, token_prefix = %s, provision_hash = NULL, "
            "       provision_expires_at = NULL, provisioned_at = now(), last_checkin_at = now(), "
            "       last_checkin_ip = %s, expires_at = now() + make_interval(days => keepalive_days), "
            "       revoked_at = NULL, revoked_by = NULL, revoke_reason = NULL "
            " WHERE id = %s RETURNING expires_at",
            (_hash(token), token[:6], request.client.host if request.client else None, rid))
        expires_at = cur.fetchone()[0]
        cur.execute(
            "SELECT u.id, u.username, coalesce(nullif(p.display_name, ''), u.username) "
            "  FROM field_relay_members m JOIN users u ON u.id = m.user_id "
            "  LEFT JOIN user_profiles p ON p.user_id = u.id "
            " WHERE m.relay_id = %s AND u.is_active ORDER BY 3", (rid,))
        roster = [{"id": r[0], "username": r[1], "name": r[2]} for r in cur.fetchall()]

    key = _identity()
    audit.record("field.relay.provision", actor_kind="relay", object_type="field_relay",
                 object_id=rid, object_label=label, detail={"team": len(roster)})
    return {"v": 1, "relay_id": rid, "label": label, "token": token,
            "keepalive_days": keepalive, "expires_at": expires_at.isoformat(),
            "addresses": addresses or [],
            "console": {"fingerprint": console_fingerprint(key),
                        "public_key": base64.b64encode(_public_der(key)).decode()},
            "roster": roster,
            "templates": {"version": templates.summary().get("version")},
            "limits": {"max_chars": field_module.MAX_SUBMISSION_CHARS,
                       "max_file_bytes": field_module.MAX_FILE_BYTES,
                       "max_submission_bytes": field_module.MAX_SUBMISSION_BYTES,
                       "max_files": field_module.MAX_FILES_PER_SUBMISSION}}


@tablet.post("/checkin")
def checkin(relay: dict = Depends(require_relay)):
    """A relay saying it is still in the right hands. Every Sync begins here."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE field_relays SET last_checkin_at = now(), last_checkin_ip = %s, "
            "       expires_at = now() + make_interval(days => keepalive_days) "
            " WHERE id = %s RETURNING expires_at, keepalive_days",
            (relay["ip"], relay["id"]))
        expires_at, keepalive = cur.fetchone()
    return {"ok": True, "label": relay["label"], "expires_at": expires_at.isoformat(),
            "keepalive_days": keepalive, "server_time": datetime.now(timezone.utc).isoformat()}


class RelayedSubmission(field_module.Submission):
    """One report, as the relay received it from a phone."""
    relay_submission_id: int = Field(ge=1)
    relay_device_id: int = Field(ge=1)
    phone_label: str | None = Field(default=None, max_length=200)
    analyst_name: str | None = Field(default=None, max_length=200)
    # The console account the lead matched this phone to, from the roster.
    analyst_user_id: int | None = None
    received_at: datetime | None = None
    priorities: list | None = None
    lead_note: str | None = Field(default=None, max_length=5000)


@tablet.post("/submissions", status_code=201)
def relayed_submission(payload: RelayedSubmission, relay: dict = Depends(require_relay)):
    if payload.criticality and payload.criticality not in field_module.CRITICALITIES:
        raise HTTPException(status_code=400,
                            detail=f"Criticality must be one of {', '.join(field_module.CRITICALITIES)}.")
    body = payload.body or ""
    if len(body) > field_module.MAX_SUBMISSION_CHARS:
        raise HTTPException(status_code=413, detail="That submission is too long.")
    fields = templates.clean_fields(payload.fields)
    template = (payload.template or "").strip()[:64] or None
    shape = field_module._clean_geometry(payload.geometry)

    with db_cursor(commit=True) as cur:
        cur.execute("SELECT id, status FROM field_submissions "
                    " WHERE relay_id = %s AND relay_submission_id = %s",
                    (relay["id"], payload.relay_submission_id))
        existing = cur.fetchone()
        if existing:
            return {"id": existing[0], "duplicate": True, "status": existing[1]}

        # Credit the analyst only if they are on this relay's team: a relay
        # must not be able to file reports under any account it names.
        user_id = None
        if payload.analyst_user_id:
            cur.execute("SELECT 1 FROM field_relay_members WHERE relay_id = %s AND user_id = %s",
                        (relay["id"], payload.analyst_user_id))
            if cur.fetchone():
                user_id = payload.analyst_user_id
        who = payload.phone_label or f"Phone {payload.relay_device_id}"
        if payload.analyst_name and user_id is None:
            who = f"{payload.analyst_name} · {who}"
        label = f"{who} (via {relay['label']})"

        cur.execute(
            "INSERT INTO field_submissions (device_id, device_label, user_id, title, body, "
            "        criticality, observed_at, lat, lng, location_accuracy_m, location_note, "
            "        client_ref, template, template_version, fields, geometry, received_at, "
            "        relay_id, relay_submission_id, relay_device_id, relay_label, relayed_at, "
            "        relay_priorities, relay_note) "
            "VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        coalesce(%s, now()), %s, %s, %s, %s, now(), %s, %s) RETURNING id",
            (label, user_id, payload.title.strip(), body or None, payload.criticality,
             payload.observed_at, payload.lat, payload.lng, payload.location_accuracy_m,
             payload.location_note, payload.client_ref, template, payload.template_version,
             json.dumps(fields), json.dumps(shape) if shape else None, payload.received_at,
             relay["id"], payload.relay_submission_id, payload.relay_device_id, relay["label"],
             json.dumps(payload.priorities) if payload.priorities else None,
             payload.lead_note))
        sid = cur.fetchone()[0]
        cur.execute("UPDATE field_relays SET submission_count = submission_count + 1 WHERE id = %s",
                    (relay["id"],))

    audit.record("field.relay.submission", actor_kind="relay", object_type="field_submission",
                 object_id=sid, object_label=payload.title.strip(),
                 detail={"relay": relay["label"], "phone": payload.phone_label,
                         "template": template})
    return {"id": sid, "duplicate": False, "status": "new"}


@tablet.post("/submissions/{submission_id}/files", status_code=201)
async def relayed_file(submission_id: int,
                       file: UploadFile = File(...),
                       client_ref: str | None = Form(default=None),
                       duration_ms: int | None = Form(default=None),
                       relay: dict = Depends(require_relay)):
    kind = (file.content_type or "").split(";")[0].strip().lower()
    if kind and not (kind.startswith(field_module.ALLOWED_MEDIA_PREFIXES)
                     or kind in field_module.ALLOWED_MEDIA_EXACT):
        raise HTTPException(status_code=415, detail=f"A relay carries pictures, audio and video. This was {kind}.")
    with db_cursor() as cur:
        cur.execute("SELECT relay_id FROM field_submissions WHERE id = %s", (submission_id,))
        row = cur.fetchone()
    if row is None or row[0] != relay["id"]:
        raise HTTPException(status_code=404, detail="No such submission.")
    return await field_module.save_submission_file(submission_id, file, client_ref, duration_ms)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class RelayCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    keepalive_days: int = Field(default=DEFAULT_KEEPALIVE, ge=1, le=MAX_KEEPALIVE)
    member_ids: list[int] = Field(default_factory=list)
    # Where the tablet looks for this console when it syncs: VPN first.
    addresses: list[str] = Field(default_factory=list)
    # Where the tablet can reach this console right now, to fetch its
    # bundle. Usually the address the admin's browser is using.
    provision_url: str | None = None


class RelayUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    keepalive_days: int | None = Field(default=None, ge=1, le=MAX_KEEPALIVE)
    member_ids: list[int] | None = None
    addresses: list[str] | None = None


class ProvisionAgain(BaseModel):
    provision_url: str | None = None


def _clean_addresses(raw: list[str]) -> list[str]:
    out = []
    for a in raw or []:
        a = (a or "").strip().rstrip("/")
        if not a:
            continue
        if not (a.startswith("http://") or a.startswith("https://")):
            raise HTTPException(status_code=400, detail=f"{a} is not an http(s) address.")
        if a not in out:
            out.append(a)
    if len(out) > 8:
        raise HTTPException(status_code=400, detail="Give at most 8 addresses.")
    return out


def _set_members(cur, relay_id: int, member_ids: list[int]):
    cur.execute("DELETE FROM field_relay_members WHERE relay_id = %s", (relay_id,))
    for uid in sorted(set(member_ids)):
        cur.execute("INSERT INTO field_relay_members (relay_id, user_id) "
                    "SELECT %s, id FROM users WHERE id = %s ON CONFLICT DO NOTHING",
                    (relay_id, uid))


def _status(revoked_at, reason, token_hash) -> str:
    if revoked_at is not None:
        return "expired" if reason == "expired" else "revoked"
    if token_hash is None:
        return "pending"
    return "active"


def _relay_rows(cur, where: str = "", params: tuple = ()) -> list:
    cur.execute(
        "SELECT r.id, r.label, r.keepalive_days, r.addresses, r.provisioned_at, r.last_checkin_at, "
        "       r.last_checkin_ip, r.expires_at, r.revoked_at, r.revoke_reason, r.submission_count, "
        "       r.created_at, cu.username, r.token_hash, r.provision_expires_at, "
        "       coalesce((SELECT json_agg(json_build_object('id', u.id, 'username', u.username, "
        "                 'name', coalesce(nullif(p.display_name, ''), u.username)) ORDER BY u.username) "
        "                   FROM field_relay_members m JOIN users u ON u.id = m.user_id "
        "                   LEFT JOIN user_profiles p ON p.user_id = u.id "
        "                  WHERE m.relay_id = r.id), '[]') "
        "  FROM field_relays r LEFT JOIN users cu ON cu.id = r.created_by "
        + where + " ORDER BY (r.revoked_at IS NOT NULL), r.created_at DESC", params)
    out = []
    for (rid, label, keepalive, addresses, provisioned_at, last_checkin, last_ip, expires_at,
         revoked_at, reason, count, created_at, created_by, token_hash, prov_until,
         members) in cur.fetchall():
        out.append({
            "id": rid, "label": label, "keepalive_days": keepalive, "addresses": addresses or [],
            "status": _status(revoked_at, reason, token_hash),
            "provisioned_at": provisioned_at.isoformat() if provisioned_at else None,
            "last_checkin_at": last_checkin.isoformat() if last_checkin else None,
            "last_checkin_ip": last_ip,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "revoked_at": revoked_at.isoformat() if revoked_at else None,
            "revoke_reason": reason, "submission_count": count,
            "created_at": created_at.isoformat() if created_at else None,
            "created_by": created_by,
            "provision_pending_until": prov_until.isoformat() if prov_until else None,
            "members": members if isinstance(members, list) else json.loads(members or "[]"),
        })
    return out


def _provision_code(cur, relay_id: int, url: str | None) -> dict:
    code = secrets.token_urlsafe(18)
    cur.execute("UPDATE field_relays SET provision_hash = %s, "
                "       provision_expires_at = now() + make_interval(mins => %s) WHERE id = %s",
                (_hash(code), PROVISION_MINUTES, relay_id))
    payload = {"v": 1, "kind": "relay-provision", "url": (url or "").strip().rstrip("/") or None,
               "code": code}
    return {"provision": payload, "provision_qr": field_module._qr_svg(json.dumps(payload)),
            "provision_minutes": PROVISION_MINUTES, "fingerprint": console_fingerprint()}


@manage.get("")
def list_relays(user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        expired = sweep_expired(cur)
        items = _relay_rows(cur)
    _audit_expired(expired)
    return {"items": items, "fingerprint": console_fingerprint(),
            "keepalive": {"default": DEFAULT_KEEPALIVE, "max": MAX_KEEPALIVE}}


@manage.post("", status_code=201)
def create_relay(payload: RelayCreate, user: dict = Depends(auth.require_admin)):
    addresses = _clean_addresses(payload.addresses)
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO field_relays (label, keepalive_days, addresses, created_by) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (payload.label.strip(), payload.keepalive_days, json.dumps(addresses), user["id"]))
        rid = cur.fetchone()[0]
        _set_members(cur, rid, payload.member_ids)
        code = _provision_code(cur, rid, payload.provision_url)
        relay = _relay_rows(cur, "WHERE r.id = %s", (rid,))[0]
    audit.record("field.relay.create", user=user, object_type="field_relay", object_id=rid,
                 object_label=payload.label.strip(),
                 detail={"keepalive_days": payload.keepalive_days, "team": len(payload.member_ids)})
    return {"relay": relay, **code}


@manage.patch("/{relay_id}")
def update_relay(relay_id: int, payload: RelayUpdate, user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT label FROM field_relays WHERE id = %s", (relay_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="No such relay.")
        if payload.label is not None:
            cur.execute("UPDATE field_relays SET label = %s WHERE id = %s", (payload.label.strip(), relay_id))
        if payload.keepalive_days is not None:
            cur.execute("UPDATE field_relays SET keepalive_days = %s WHERE id = %s",
                        (payload.keepalive_days, relay_id))
        if payload.addresses is not None:
            cur.execute("UPDATE field_relays SET addresses = %s WHERE id = %s",
                        (json.dumps(_clean_addresses(payload.addresses)), relay_id))
        if payload.member_ids is not None:
            _set_members(cur, relay_id, payload.member_ids)
        relay = _relay_rows(cur, "WHERE r.id = %s", (relay_id,))[0]
    audit.record("field.relay.update", user=user, object_type="field_relay", object_id=relay_id,
                 object_label=relay["label"])
    return relay


@manage.post("/{relay_id}/provision", status_code=201)
def provision_again(relay_id: int, payload: ProvisionAgain, user: dict = Depends(auth.require_admin)):
    """A fresh one-time code, for a relay back from a deployment whose key
    expired, or a tablet being set up again. Exchanging it issues a new key
    and the old one stops working at that moment."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT label FROM field_relays WHERE id = %s", (relay_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such relay.")
        code = _provision_code(cur, relay_id, payload.provision_url)
        relay = _relay_rows(cur, "WHERE r.id = %s", (relay_id,))[0]
    audit.record("field.relay.reprovision", user=user, object_type="field_relay",
                 object_id=relay_id, object_label=row[0])
    return {"relay": relay, **code}


@manage.post("/{relay_id}/extend")
def extend_relay(relay_id: int, user: dict = Depends(auth.require_admin)):
    """Restart the keep-alive clock from now, for a team that has told you
    by other means that they and the tablet are fine."""
    with db_cursor(commit=True) as cur:
        expired = sweep_expired(cur)
        cur.execute("SELECT label, revoked_at, token_hash FROM field_relays WHERE id = %s", (relay_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such relay.")
        if row[1] is not None:
            raise HTTPException(status_code=409,
                                detail="That relay's key is already gone. Re-provision it in person.")
        if row[2] is None:
            raise HTTPException(status_code=409, detail="That relay has not been provisioned yet.")
        cur.execute("UPDATE field_relays SET expires_at = now() + make_interval(days => keepalive_days) "
                    " WHERE id = %s", (relay_id,))
        relay = _relay_rows(cur, "WHERE r.id = %s", (relay_id,))[0]
    _audit_expired(expired)
    audit.record("field.relay.extend", user=user, object_type="field_relay", object_id=relay_id,
                 object_label=row[0])
    return relay


@manage.post("/{relay_id}/revoke")
def revoke_relay(relay_id: int, user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT label, revoked_at FROM field_relays WHERE id = %s", (relay_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such relay.")
        if row[1] is None:
            cur.execute("UPDATE field_relays SET revoked_at = now(), revoked_by = %s, "
                        "       revoke_reason = 'manual', provision_hash = NULL WHERE id = %s",
                        (user["id"], relay_id))
    audit.record("field.relay.revoke", user=user, object_type="field_relay", object_id=relay_id,
                 object_label=row[0])
    return {"id": relay_id, "revoked": True}


@manage.delete("/{relay_id}", status_code=204)
def delete_relay(relay_id: int, user: dict = Depends(auth.require_admin)):
    """Remove the relay's record. What it delivered stays: each submission
    carries a copy of the relay's name."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT label FROM field_relays WHERE id = %s", (relay_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such relay.")
        cur.execute("DELETE FROM field_relays WHERE id = %s", (relay_id,))
    audit.record("field.relay.delete", user=user, object_type="field_relay", object_id=relay_id,
                 object_label=row[0])
