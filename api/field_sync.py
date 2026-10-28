"""Field server → HQ case sync.

A field server (the Pi appliance, or any console taken off-site) works on a
copy of the case for days. This is how what it learned comes home WITHOUT
overwriting what HQ learned in the meantime.

THE SHAPE OF IT

  On the field server   Admin → Field sync → Export. A .zip "field package"
                        of everything created or changed there since it was
                        seeded from HQ (or since its last export).

  At HQ                 Admin → Field sync → Import. Nothing is written to the
                        case file. Instead:

    - a record the field server CREATED becomes a proposal in the review
      queue, with any HQ records that look like the same thing named beside
      it, so the reviewer either accepts it as new or says "this is X we
      already have" (de-duplication, decided by a person);
    - a record HQ already had and the field server CHANGED becomes a proposal
      listing each changed field, HQ's value against the field's, and the
      reviewer applies the changes they agree with;
    - a relationship becomes a relationship proposal, whose ends fill in by
      themselves as their records are accepted;
    - a report, or a phone report the field server had not yet promoted,
      lands in the Field inbox, where reports from phones already go, and is
      promoted to a draft report the usual way.

  That is the app's standing rule — a person decides what enters the case
  file — applied to a whole deployment's work at once.

IDENTITY

Every console has an instance_uuid of its own (instance_identity), which a
backup never carries and a restore never wipes. Records a field server made
are remembered at HQ by (origin, field id) → HQ id, so a second package from
the same box finds the records the first one created, and a relationship
whose ends were accepted from an earlier package resolves on its own.

WHAT IS NOT CARRIED (v1)

Zones and routes (their geometry has its own timeline), documents not filed
against a report, entity photos, boards and map packs. Deleting a record on
the field server is not propagated — archive it there and the archive comes
home as a proposed change.
"""

import io
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from psycopg2.extras import Json
from starlette.background import BackgroundTask

import audit
import auth
import entities as entities_module
from backup import _json_default, _read_upload_to_temp, _safe_upload_path, UPLOAD_DIR
from db import db_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/field-sync", tags=["field-sync"])

PACKAGE_FORMAT = "humint-field-package"
PACKAGE_VERSION = 1

# Kinds whose shape this package carries faithfully. Zones and routes keep a
# geometry timeline in their own tables; carrying them half-way would be
# worse than leaving them to be redrawn.
SYNC_TYPES = ("person", "organization", "location", "event", "source",
              "communication", "vehicle", "record")

# The fields a change proposal can name. Anything else on the row (embedding,
# retention bookkeeping) is this console's business, not the case's.
CORE_FIELDS = ("name", "description", "is_active")


# ----------------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------------

def _identity(cur) -> dict:
    cur.execute("SELECT instance_uuid, seeded_at FROM instance_identity WHERE id = 1")
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO instance_identity (id, instance_uuid) VALUES (1, %s) "
                    "ON CONFLICT (id) DO NOTHING", (uuid.uuid4().hex,))
        cur.execute("SELECT instance_uuid, seeded_at FROM instance_identity WHERE id = 1")
        row = cur.fetchone()
    return {"instance_uuid": row[0], "seeded_at": row[1]}


def mark_seeded() -> None:
    """Called after a restore: everything this console now holds, the console
    the backup came from already has."""
    with db_cursor(commit=True) as cur:
        _identity(cur)
        cur.execute("UPDATE instance_identity SET seeded_at = now() WHERE id = 1")


def _instance_name(cur) -> str:
    try:
        import branding
        return branding._effective(cur).get("instance_name") or "Field server"
    except Exception:
        return os.environ.get("INSTANCE_NAME", "Field server")


def _since(cur, mode: str):
    ident = _identity(cur)
    if mode == "everything":
        return None
    cur.execute("SELECT max(exported_at) FROM field_sync_exports")
    last_export = cur.fetchone()[0]
    seeded = ident["seeded_at"]
    if mode == "since_seeded":
        return seeded
    # since_last (default): the later of the two. An export before the
    # restore that seeded this box is from a different life of it.
    stamps = [t for t in (seeded, last_export) if t is not None]
    return max(stamps) if stamps else None


# ----------------------------------------------------------------------------
# Field side: status and export
# ----------------------------------------------------------------------------

def _changed_counts(cur, since) -> dict:
    cond, params = ("> %s", [since]) if since else ("IS NOT NULL", [])
    types = list(SYNC_TYPES)
    cur.execute(f"SELECT count(*) FROM entities WHERE entity_type = ANY(%s) "
                f"AND (created_at {cond} OR updated_at {cond})",
                [types, *params, *params])
    ents = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM relationships WHERE created_at {cond}", params)
    rels = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM reports WHERE created_at {cond} OR updated_at {cond}",
                [*params, *params])
    reps = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM field_submissions WHERE status = 'new' "
                f"AND received_at {cond}", params)
    subs = cur.fetchone()[0]
    return {"entities": ents, "relationships": rels, "reports": reps,
            "submissions": subs}


@router.get("/status")
def sync_status(user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        ident = _identity(cur)
        since = _since(cur, "since_last")
        cur.execute("SELECT package_id, since, exported_at, counts FROM field_sync_exports "
                    "ORDER BY exported_at DESC LIMIT 5")
        exports = [{"package_id": r[0], "since": r[1], "exported_at": r[2], "counts": r[3]}
                   for r in cur.fetchall()]
        cur.execute("SELECT id, package_id, origin_name, exported_at, imported_at, counts, "
                    "       (SELECT count(*) FROM extraction_suggestions s "
                    "         WHERE s.field_import_id = i.id AND s.status = 'pending'), "
                    "       (SELECT count(*) FROM field_submissions f "
                    "         WHERE f.field_import_id = i.id AND f.status = 'new') "
                    "  FROM field_imports i ORDER BY imported_at DESC LIMIT 20")
        imports = [{"id": r[0], "package_id": r[1], "origin_name": r[2],
                    "exported_at": r[3], "imported_at": r[4], "counts": r[5],
                    "pending_proposals": r[6], "pending_reports": r[7]}
                   for r in cur.fetchall()]
        pending = _changed_counts(cur, since)
        return {"instance_uuid": ident["instance_uuid"],
                "instance_name": _instance_name(cur),
                "seeded_at": ident["seeded_at"], "since": since,
                "pending_export": pending, "exports": exports, "imports": imports}


def _entity_rows(cur, since) -> list[dict]:
    cond, params = ("> %s", [since]) if since else ("IS NOT NULL", [])
    cur.execute(
        "SELECT id, entity_type, name, description, is_active, merged_into, "
        "       created_at, updated_at "
        f"  FROM entities WHERE entity_type = ANY(%s) "
        f"   AND (created_at {cond} OR updated_at {cond}) ORDER BY created_at, id",
        [list(SYNC_TYPES), *params, *params])
    rows = []
    for (eid, etype, name, desc, active, merged, created, updated) in cur.fetchall():
        details = entities_module._fetch_details(cur, etype, eid)
        rows.append({
            "id": eid, "entity_type": etype, "name": name, "description": desc,
            "is_active": active, "merged_into": merged,
            "created_at": created, "updated_at": updated,
            "existed_at_since": bool(since and created <= since),
            "details": {k: v for k, v in details.items() if v is not None},
        })
    return rows


def _relationship_rows(cur, since) -> list[dict]:
    cond, params = ("> %s", [since]) if since else ("IS NOT NULL", [])
    cur.execute(
        "SELECT r.id, r.from_entity_id, f.name, f.entity_type, r.to_entity_id, t.name, "
        "       t.entity_type, r.relationship_type, r.confidence, r.discovery_date, "
        "       r.expires_on, r.notes, r.created_at "
        "  FROM relationships r JOIN entities f ON f.id = r.from_entity_id "
        "  JOIN entities t ON t.id = r.to_entity_id "
        f" WHERE r.created_at {cond} ORDER BY r.id", params)
    keys = ("id", "from_id", "from_name", "from_type", "to_id", "to_name", "to_type",
            "relationship_type", "confidence", "discovery_date", "expires_on", "notes",
            "created_at")
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def _report_rows(cur, since, zf) -> list[dict]:
    cond, params = ("> %s", [since]) if since else ("IS NOT NULL", [])
    cur.execute(
        "SELECT r.id, r.title, r.body_markdown, r.status, r.credibility_rating, "
        "       r.criticality, u.username, r.created_at, r.updated_at "
        "  FROM reports r LEFT JOIN users u ON u.id = r.author_id "
        f" WHERE r.created_at {cond} OR r.updated_at {cond} ORDER BY r.created_at",
        [*params, *params])
    keys = ("id", "title", "body_markdown", "status", "credibility_rating",
            "criticality", "author", "created_at", "updated_at")
    reports = [dict(zip(keys, r)) for r in cur.fetchall()]
    for rep in reports:
        cur.execute("SELECT e.id, e.name, e.entity_type FROM report_entities re "
                    "  JOIN entities e ON e.id = re.entity_id WHERE re.report_id = %s",
                    (rep["id"],))
        rep["entities"] = [{"id": a, "name": b, "entity_type": c} for a, b, c in cur.fetchall()]
        cur.execute("SELECT id, filename, title, storage_path, mime_type, file_size_bytes "
                    "  FROM attachments WHERE report_id = %s ORDER BY id", (rep["id"],))
        rep["files"] = _pack_files(zf, [
            {"key": f"att-{a}", "filename": fn, "title": t, "storage_path": sp,
             "mime_type": mt, "size": sz} for a, fn, t, sp, mt, sz in cur.fetchall()])
    return reports


def _submission_rows(cur, since, zf) -> list[dict]:
    cond, params = ("> %s", [since]) if since else ("IS NOT NULL", [])
    cur.execute(
        "SELECT id, device_label, title, body, template, template_version, fields, "
        "       criticality, observed_at, lat, lng, location_accuracy_m, location_note, "
        "       geometry, received_at "
        f"  FROM field_submissions WHERE status = 'new' AND received_at {cond} "
        "  ORDER BY received_at", params)
    keys = ("id", "device_label", "title", "body", "template", "template_version",
            "fields", "criticality", "observed_at", "lat", "lng", "location_accuracy_m",
            "location_note", "geometry", "received_at")
    subs = [dict(zip(keys, r)) for r in cur.fetchall()]
    for sub in subs:
        cur.execute("SELECT id, filename, storage_path, mime_type, file_size_bytes, duration_ms "
                    "  FROM field_submission_files WHERE submission_id = %s ORDER BY id",
                    (sub["id"],))
        sub["files"] = _pack_files(zf, [
            {"key": f"sub-{a}", "filename": fn, "storage_path": sp, "mime_type": mt,
             "size": sz, "duration_ms": dur}
            for a, fn, sp, mt, sz, dur in cur.fetchall()])
    return subs


def _pack_files(zf, files: list[dict]) -> list[dict]:
    """Copy each file into the package under files/, keyed by its own row,
    and drop the storage path: HQ decides where it lives there."""
    out = []
    for f in files:
        src = _safe_upload_path(f.pop("storage_path"))
        if not src or not os.path.isfile(src):
            f["missing"] = True
            out.append(f)
            continue
        ext = os.path.splitext(f.get("filename") or "")[1][:12]
        arc = f"files/{f['key']}{ext}"
        zf.write(src, arc)
        f["path"] = arc
        out.append(f)
    return out


@router.post("/export")
def export_package(payload: dict = Body(default={}), user: dict = Depends(auth.require_admin)):
    mode = (payload or {}).get("mode", "since_last")
    if mode not in ("since_last", "since_seeded", "everything"):
        raise HTTPException(status_code=400,
                            detail="mode must be since_last, since_seeded or everything")
    package_id = uuid.uuid4().hex
    exported_at = datetime.now(timezone.utc)
    tmp_dir = tempfile.mkdtemp(prefix="humint-field-")
    try:
        with db_cursor(commit=True) as cur:
            ident = _identity(cur)
            since = _since(cur, mode)
            name = _instance_name(cur)
            stamp = exported_at.strftime("%Y%m%d-%H%M")
            safe = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40] or "field"
            filename = f"{safe}-field-package-{stamp}.zip"
            zip_path = os.path.join(tmp_dir, filename)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                data = {
                    "entities": _entity_rows(cur, since),
                    "relationships": _relationship_rows(cur, since),
                    "reports": _report_rows(cur, since, zf),
                    "submissions": _submission_rows(cur, since, zf),
                }
                counts = {k: len(v) for k, v in data.items()}
                manifest = {
                    "format": PACKAGE_FORMAT, "format_version": PACKAGE_VERSION,
                    "package_id": package_id, "origin_id": ident["instance_uuid"],
                    "origin_name": name, "exported_at": exported_at.isoformat(),
                    "exported_by": user["username"],
                    "since": since.isoformat() if since else None, "mode": mode,
                    "counts": counts,
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                zf.writestr("data.json", json.dumps(data, indent=1, default=_json_default))
            cur.execute("INSERT INTO field_sync_exports (package_id, since, exported_at, "
                        "exported_by, counts) VALUES (%s, %s, %s, %s, %s)",
                        (package_id, since, exported_at, user["id"], Json(counts)))
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    audit.record("field_sync.export", user=user, object_type="field_package",
                 object_id=package_id, object_label=filename,
                 detail={"since": manifest["since"], "counts": counts,
                         "size_bytes": os.path.getsize(zip_path)})
    return FileResponse(zip_path, media_type="application/zip", filename=filename,
                        background=BackgroundTask(shutil.rmtree, tmp_dir, True))


# ----------------------------------------------------------------------------
# HQ side: import
# ----------------------------------------------------------------------------

def _read_package(zip_path: str) -> tuple[dict, dict, zipfile.ZipFile]:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="That is not a field package (not a zip file).")
    for info in zf.infolist():
        n = info.filename
        if n.startswith("/") or ".." in n.split("/") or "\\" in n or "\x00" in n:
            raise HTTPException(status_code=400, detail="That package contains unsafe paths.")
    try:
        manifest = json.loads(zf.read("manifest.json"))
        data = json.loads(zf.read("data.json"))
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="That package is missing its manifest or data.")
    if manifest.get("format") != PACKAGE_FORMAT:
        raise HTTPException(status_code=400,
                            detail="That is not a field package. (A whole-console backup is "
                                   "restored under Backup, not imported here.)")
    if int(manifest.get("format_version") or 0) > PACKAGE_VERSION:
        raise HTTPException(status_code=400,
                            detail="That package is from a newer version of the app. Update this console first.")
    for key in ("package_id", "origin_id"):
        if not manifest.get(key):
            raise HTTPException(status_code=400, detail=f"The package manifest has no {key}.")
    return manifest, data, zf


def _resolve(cur, origin: str, field_id: str):
    """The HQ record a field-server record id stands for, if there is one: the
    same id (the field server was seeded from HQ), or what an earlier import
    mapped it to."""
    if not field_id:
        return None
    if entities_module._entity_exists(cur, field_id):
        return field_id
    cur.execute("SELECT hq_entity_id FROM field_import_map "
                " WHERE origin_id = %s AND field_entity_id = %s", (origin, field_id))
    row = cur.fetchone()
    return row[0] if row else None


def _norm(value):
    """Both sides as JSON would carry them, so a date is not "changed" for
    having crossed the wire as a string."""
    if value is None:
        return None
    from decimal import Decimal
    if isinstance(value, Decimal):
        value = float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _diff(cur, hq_id: str, ent: dict) -> list[dict]:
    cur.execute("SELECT entity_type, name, description, is_active FROM entities WHERE id = %s",
                (hq_id,))
    etype, name, desc, active = cur.fetchone()
    hq = {"name": name, "description": desc, "is_active": active}
    changes = []
    for key in CORE_FIELDS:
        a, b = _norm(hq[key]), _norm(ent.get(key))
        if key == "description":
            a, b = a or None, b or None
        if a != b:
            changes.append({"field": key, "hq": a, "field_value": b})
    if etype == ent.get("entity_type"):
        hq_details = entities_module._fetch_details(cur, etype, hq_id)
        for key, value in (ent.get("details") or {}).items():
            if key not in hq_details:
                continue
            a, b = _norm(hq_details.get(key)), _norm(value)
            if a != b and b not in (None, "", []):
                changes.append({"field": f"details.{key}", "hq": a, "field_value": b})
    return changes


_NOISE = {"ltd", "limited", "inc", "llc", "co", "corp", "company", "the", "plc", "gmbh", "sa"}


def _fold(text: str) -> str:
    """Kovač and Kovac are the same name to a reviewer; make them the same
    string here too."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(c))


def _tokens(name: str) -> list[str]:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in _fold(name))
    return [t for t in cleaned.split() if t not in _NOISE]


def _likeness(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    sa, sb = set(ta), set(tb)
    if sa <= sb or sb <= sa:
        return 0.85                 # "Marek Hale" / "Marek J. Hale"
    return len(sa & sb) / len(sa | sb)


def _possible_matches(cur, etype: str, name: str) -> list[dict]:
    """HQ records that may be the same thing, for the reviewer to choose from.
    Deliberately generous — a wrong suggestion costs a glance, a missed
    duplicate costs a split record — and deliberately never acted on alone."""
    toks = _tokens(name)
    if not toks:
        return []
    # Any HQ record of the same kind sharing a meaningful word, then scored.
    raw = [t for t in "".join(c.lower() if c.isalnum() else " " for c in name).split()]
    patterns = sorted({f"%{t}%" for t in toks + raw if len(t) >= 3}) or [f"%{toks[0]}%"]
    cur.execute(
        "SELECT id, name, entity_type FROM entities "
        " WHERE entity_type = %s AND is_active AND merged_into IS NULL "
        "   AND name ILIKE ANY(%s) LIMIT 200", (etype, patterns))
    scored = []
    for eid, ename, etyp in cur.fetchall():
        score = _likeness(name, ename)
        if score >= 0.5:
            scored.append({"id": eid, "name": ename, "entity_type": etyp,
                           "likeness": round(score, 2)})
    scored.sort(key=lambda m: (-m["likeness"], m["name"]))
    return scored[:5]


def _supersede(cur, origin: str, key: str, value: str) -> None:
    """A newer package's word about a record replaces an older one still
    waiting in the queue — reviewing a stale version first would be wasted
    work, or worse, applied."""
    cur.execute(
        "UPDATE extraction_suggestions SET status = 'rejected', reviewed_at = now(), "
        "       evidence = evidence || '{\"superseded\": true}'::jsonb "
        " WHERE source = 'field' AND status = 'pending' AND suggestion_type = 'entity' "
        "   AND evidence->>'origin_id' = %s AND evidence->>%s = %s",
        (origin, key, value))


def _import_entities(cur, manifest, data, import_id) -> dict:
    origin, origin_name = manifest["origin_id"], manifest.get("origin_name")
    counts = {"new": 0, "changed": 0, "unchanged": 0, "skipped": 0}
    for ent in data.get("entities") or []:
        etype = ent.get("entity_type")
        if etype not in SYNC_TYPES or not ent.get("id") or not ent.get("name"):
            counts["skipped"] += 1
            continue
        if ent.get("merged_into"):
            # Merged away on the field server: the survivor carries it home.
            counts["skipped"] += 1
            continue
        base = {"origin_id": origin, "origin_name": origin_name,
                "field_entity_id": ent["id"],
                "field_updated_at": ent.get("updated_at")}
        hq_id = _resolve(cur, origin, ent["id"])
        if hq_id:
            changes = _diff(cur, hq_id, ent)
            if not changes:
                counts["unchanged"] += 1
                continue
            _supersede(cur, origin, "entity_id", hq_id)
            evidence = dict(base, kind="field_edit", entity_id=hq_id, changes=changes)
            details = {c["field"][8:]: c["field_value"] for c in changes
                       if c["field"].startswith("details.")}
            counts["changed"] += 1
        else:
            _supersede(cur, origin, "field_entity_id", ent["id"])
            evidence = dict(base, kind="field_new", description=ent.get("description"),
                            is_active=ent.get("is_active", True),
                            possible_matches=_possible_matches(cur, etype, ent["name"]))
            details = ent.get("details") or {}
            counts["new"] += 1
        cur.execute(
            "INSERT INTO extraction_suggestions (source, suggestion_type, suggested_entity_type, "
            "       suggested_name, details, evidence, field_import_id) "
            "VALUES ('field', 'entity', %s, %s, %s, %s, %s)",
            (etype, ent["name"], Json(details, dumps=lambda o: json.dumps(o, default=_json_default)),
             Json(evidence, dumps=lambda o: json.dumps(o, default=_json_default)), import_id))
    return counts


def _import_relationships(cur, manifest, data, import_id) -> dict:
    origin, origin_name = manifest["origin_id"], manifest.get("origin_name")
    counts = {"proposed": 0, "already_known": 0, "skipped": 0}
    for rel in data.get("relationships") or []:
        rtype = (rel.get("relationship_type") or "").strip().lower()
        if not rtype or not rel.get("from_id") or not rel.get("to_id"):
            counts["skipped"] += 1
            continue
        from_id = _resolve(cur, origin, rel["from_id"])
        to_id = _resolve(cur, origin, rel["to_id"])
        if from_id and to_id:
            cur.execute("SELECT 1 FROM relationships WHERE from_entity_id = %s "
                        "AND to_entity_id = %s AND relationship_type = %s",
                        (from_id, to_id, rtype))
            if cur.fetchone():
                counts["already_known"] += 1
                continue
        evidence = {"kind": "field_link", "origin_id": origin, "origin_name": origin_name,
                    "field_from_id": rel["from_id"], "field_to_id": rel["to_id"],
                    "from_type": rel.get("from_type"), "to_type": rel.get("to_type"),
                    "confidence": rel.get("confidence"),
                    "discovery_date": rel.get("discovery_date"),
                    "expires_on": rel.get("expires_on"), "notes": rel.get("notes")}
        cur.execute(
            "INSERT INTO extraction_suggestions (source, suggestion_type, "
            "       suggested_relationship_type, suggested_from_name, suggested_to_name, "
            "       suggested_from_entity_id, suggested_to_entity_id, evidence, field_import_id) "
            "VALUES ('field', 'relationship', %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (rtype, rel.get("from_name"), rel.get("to_name"), from_id, to_id,
             Json(evidence, dumps=lambda o: json.dumps(o, default=_json_default)), import_id))
        counts["proposed" if cur.rowcount else "already_known"] += 1
    return counts


def _store_files(zf, files: list[dict], import_dir_rel: str, written: list) -> list[tuple]:
    out = []
    for f in files or []:
        arc = f.get("path")
        if not arc or f.get("missing"):
            continue
        try:
            info = zf.getinfo(arc)
        except KeyError:
            continue
        ext = os.path.splitext(f.get("filename") or arc)[1][:12]
        rel = os.path.join(import_dir_rel, f"{uuid.uuid4().hex}{ext}")
        dest = _safe_upload_path(rel)
        if not dest:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as out_fh:
            shutil.copyfileobj(src, out_fh)
        written.append(dest)
        mime = f.get("mime_type") or mimetypes.guess_type(f.get("filename") or "")[0]
        out.append((os.path.basename(f.get("filename") or "file"), rel, mime,
                    info.file_size, f.get("duration_ms")))
    return out


def _insert_submission(cur, values: dict, files: list[tuple]) -> bool:
    cols = list(values)
    cur.execute(
        f"INSERT INTO field_submissions ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING RETURNING id",
        [Json(v) if isinstance(v, (dict, list)) else v for v in values.values()])
    row = cur.fetchone()
    if row is None:
        return False
    for name, rel, mime, size, dur in files:
        cur.execute("INSERT INTO field_submission_files (submission_id, filename, storage_path, "
                    "mime_type, file_size_bytes, duration_ms) VALUES (%s, %s, %s, %s, %s, %s)",
                    (row[0], name, rel, mime, size, dur))
    return True


def _hq_user(cur, username):
    if not username:
        return None
    cur.execute("SELECT id FROM users WHERE lower(username) = lower(%s)", (username,))
    row = cur.fetchone()
    return row[0] if row else None


def _import_reports(cur, manifest, data, import_id, zf, written) -> dict:
    import reports as reports_module
    origin, origin_name = manifest["origin_id"], manifest.get("origin_name") or "field server"
    rel_dir = os.path.join("field-imports", str(import_id))
    counts = {"reports": 0, "phone_reports": 0, "already_imported": 0}

    for rep in data.get("reports") or []:
        ref = f"{origin}:report:{rep.get('id')}:{rep.get('updated_at')}"
        cur.execute("SELECT 1 FROM field_submissions WHERE field_origin_ref = %s", (ref,))
        if cur.fetchone():
            counts["already_imported"] += 1
            continue
        crit = rep.get("criticality") if rep.get("criticality") in reports_module.CRITICALITY_LEVELS else None
        when = rep.get("created_at")
        head = [f"*Written on {origin_name}"
                + (f" by {rep['author']}" if rep.get("author") else "")
                + (f", {str(when)[:16].replace('T', ' ')} UTC" if when else "") + ".*"]
        bits = []
        if rep.get("credibility_rating"):
            bits.append(f"credibility {rep['credibility_rating']}")
        if rep.get("status"):
            bits.append(f"{rep['status']} there")
        if bits:
            head.append("*" + ", ".join(bits).capitalize() + ".*")
        linked = rep.get("entities") or []
        tail = ""
        if linked:
            tail = "\n\n*Linked there to: " + ", ".join(
                f"{e.get('name')} ({e.get('entity_type')})" for e in linked) + ".*"
        body = "\n".join(head) + "\n\n" + (rep.get("body_markdown") or "") + tail
        files = _store_files(zf, rep.get("files"), rel_dir, written)
        made = _insert_submission(cur, {
            "device_label": f"Field server · {origin_name}",
            "user_id": _hq_user(cur, rep.get("author")),
            "title": (rep.get("title") or "Untitled field report")[:300],
            "body": body, "criticality": crit, "observed_at": when,
            "field_import_id": import_id, "field_origin_ref": ref,
            "link_entities": linked,
        }, files)
        counts["reports" if made else "already_imported"] += 1

    for sub in data.get("submissions") or []:
        ref = f"{origin}:submission:{sub.get('id')}"
        cur.execute("SELECT 1 FROM field_submissions WHERE field_origin_ref = %s", (ref,))
        if cur.fetchone():
            counts["already_imported"] += 1
            continue
        crit = sub.get("criticality") if sub.get("criticality") in reports_module.CRITICALITY_LEVELS else None
        files = _store_files(zf, sub.get("files"), rel_dir, written)
        made = _insert_submission(cur, {
            "device_label": f"{sub.get('device_label') or 'a phone'} (via {origin_name})",
            "title": (sub.get("title") or "Field report")[:300], "body": sub.get("body"),
            "template": sub.get("template"), "template_version": sub.get("template_version"),
            "fields": sub.get("fields") or {}, "criticality": crit,
            "observed_at": sub.get("observed_at"), "lat": sub.get("lat"), "lng": sub.get("lng"),
            "location_accuracy_m": sub.get("location_accuracy_m"),
            "location_note": sub.get("location_note"), "geometry": sub.get("geometry"),
            "field_import_id": import_id, "field_origin_ref": ref,
        }, files)
        counts["phone_reports" if made else "already_imported"] += 1
    return counts


@router.post("/import")
def import_package(file: UploadFile = File(...), user: dict = Depends(auth.require_admin)):
    tmp_dir = tempfile.mkdtemp(prefix="humint-field-import-")
    written: list[str] = []
    try:
        zip_path = _read_upload_to_temp(file, tmp_dir)
        manifest, data, zf = _read_package(zip_path)
        with zf, db_cursor(commit=True) as cur:
            ident = _identity(cur)
            if manifest["origin_id"] == ident["instance_uuid"]:
                raise HTTPException(status_code=400,
                                    detail="That package was exported from this console. Import it at HQ.")
            cur.execute("SELECT imported_at FROM field_imports WHERE package_id = %s",
                        (manifest["package_id"],))
            row = cur.fetchone()
            if row:
                raise HTTPException(status_code=409,
                                    detail=f"That package was already imported, on {row[0]:%Y-%m-%d %H:%M}.")
            cur.execute(
                "INSERT INTO field_imports (package_id, origin_id, origin_name, exported_at, "
                "       since, imported_by) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (manifest["package_id"], manifest["origin_id"], manifest.get("origin_name"),
                 manifest.get("exported_at"), manifest.get("since"), user["id"]))
            import_id = cur.fetchone()[0]
            counts = {
                "entities": _import_entities(cur, manifest, data, import_id),
                "relationships": _import_relationships(cur, manifest, data, import_id),
                "inbox": _import_reports(cur, manifest, data, import_id, zf, written),
            }
            cur.execute("UPDATE field_imports SET counts = %s WHERE id = %s",
                        (Json(counts), import_id))
    except BaseException:
        # The database half rolled back; take the files it would have pointed at
        # with it, so a failed import leaves nothing behind.
        for path in written:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    audit.record("field_sync.import", user=user, object_type="field_package",
                 object_id=manifest["package_id"],
                 object_label=f"{manifest.get('origin_name')} · {manifest.get('exported_at')}",
                 detail={"import_id": import_id, "counts": counts})
    return {"import_id": import_id, "origin_name": manifest.get("origin_name"),
            "exported_at": manifest.get("exported_at"), "counts": counts}


# ----------------------------------------------------------------------------
# Accepting field proposals (called from the review queue's accept endpoint)
# ----------------------------------------------------------------------------

def _map(cur, origin: str, field_id: str, hq_id: str, import_id, user: dict) -> None:
    cur.execute(
        "INSERT INTO field_import_map (origin_id, field_entity_id, hq_entity_id, import_id, mapped_by) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (origin_id, field_entity_id) "
        "DO UPDATE SET hq_entity_id = EXCLUDED.hq_entity_id, mapped_at = now(), "
        "              mapped_by = EXCLUDED.mapped_by",
        (origin, field_id, hq_id, import_id, user["id"]))
    # Relationship proposals waiting on this record now know one of their ends.
    for side in ("from", "to"):
        cur.execute(
            f"SELECT id FROM extraction_suggestions WHERE source = 'field' AND status = 'pending' "
            f"   AND suggestion_type = 'relationship' AND suggested_{side}_entity_id IS NULL "
            f"   AND evidence->>'origin_id' = %s AND evidence->>'field_{side}_id' = %s",
            (origin, field_id))
        for (sid,) in cur.fetchall():
            cur.execute("SAVEPOINT fill_end")
            try:
                cur.execute(f"UPDATE extraction_suggestions SET suggested_{side}_entity_id = %s "
                            " WHERE id = %s", (hq_id, sid))
                cur.execute("RELEASE SAVEPOINT fill_end")
            except Exception:
                # The same link is already waiting from another source: leave
                # this one to be settled by hand rather than fail the accept.
                cur.execute("ROLLBACK TO SAVEPOINT fill_end")


def _apply_changes(cur, hq_id: str, changes: list[dict], apply) -> list[str]:
    cur.execute("SELECT entity_type FROM entities WHERE id = %s", (hq_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="The record this change is for no longer exists.")
    etype = row[0]
    chosen = [c for c in changes if apply is None or c["field"] in apply]
    if not chosen:
        raise HTTPException(status_code=400, detail="Choose at least one change to apply, or dismiss it.")
    core = {c["field"]: c["field_value"] for c in chosen if c["field"] in CORE_FIELDS}
    if "name" in core and not (core["name"] or "").strip():
        raise HTTPException(status_code=422, detail="A record needs a name.")
    if core:
        extra = ", archived_reason = NULL" if core.get("is_active") is True else ""
        set_clause = ", ".join(f"{k} = %s" for k in core)
        cur.execute(f"UPDATE entities SET {set_clause}, updated_at = now(), "
                    f"retention_due_at = NULL{extra} WHERE id = %s", [*core.values(), hq_id])
    details = {c["field"][8:]: c["field_value"] for c in chosen if c["field"].startswith("details.")}
    if details:
        model = entities_module.DETAIL_MODELS[etype]
        details = {k: v for k, v in details.items() if k in model.model_fields}
        try:
            coerced = model(**details).model_dump(include=set(details))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid details for {etype}: {exc}")
        entities_module._update_details(cur, etype, hq_id, coerced)
        if not core:
            cur.execute("UPDATE entities SET updated_at = now() WHERE id = %s", (hq_id,))
        if etype == "location":
            cur.execute("SELECT address, lat, lng FROM location_details WHERE entity_id = %s", (hq_id,))
            addr, lat, lng = cur.fetchone()
            entities_module._apply_location_derived_fields(cur, hq_id, addr, lat, lng)
    return [c["field"] for c in chosen]


def accept_in_queue(cur, suggestion: dict, payload: dict, user: dict):
    """Accept a proposal that came from a field package. Returns the response
    for an entity proposal; for a relationship it fills in what the field
    server knew (its ends, its grading) and returns None, so the ordinary
    relationship accept — the same validation as typing it — does the rest."""
    import extraction as extraction_module
    ev = suggestion.get("evidence") or {}
    kind = ev.get("kind")
    origin = ev.get("origin_id")
    payload = payload if isinstance(payload, dict) else {}

    if suggestion["suggestion_type"] == "relationship":
        for side in ("from", "to"):
            if not suggestion.get(f"suggested_{side}_entity_id"):
                hq = _resolve(cur, origin, ev.get(f"field_{side}_id"))
                if hq:
                    suggestion[f"suggested_{side}_entity_id"] = hq
        if ev.get("confidence") in ("1", "2", "3", "4", "5", "6"):
            payload.setdefault("confidence", ev["confidence"])
        if ev.get("discovery_date"):
            payload.setdefault("discovery_date", str(ev["discovery_date"])[:10])
        note = ev.get("notes")
        stamp = f"From field server {ev.get('origin_name') or ''}".strip()
        payload.setdefault("notes", f"{note}\n\n{stamp}" if note else stamp)
        return None

    if kind == "field_edit":
        hq_id = ev.get("entity_id")
        applied = _apply_changes(cur, hq_id, ev.get("changes") or [], payload.get("apply"))
        cur.execute("UPDATE extraction_suggestions SET status = 'accepted', resolved_entity_id = %s, "
                    "reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                    (hq_id, user["id"], suggestion["id"]))
        if ev.get("field_entity_id") and ev["field_entity_id"] != hq_id:
            _map(cur, origin, ev["field_entity_id"], hq_id, suggestion.get("field_import_id"), user)
        audit.record("entity.update", user=user, object_type="entity", object_id=hq_id,
                     object_label=suggestion.get("suggested_name"),
                     detail={"fields": applied, "via": "field_sync",
                             "origin": ev.get("origin_name"), "suggestion_id": suggestion["id"]})
        return {"id": suggestion["id"], "status": "accepted", "resolved_entity_id": hq_id,
                "applied": applied}

    # field_new
    existing = payload.get("use_existing_entity_id")
    if existing:
        if not entities_module._entity_exists(cur, existing):
            raise HTTPException(status_code=404, detail="That record does not exist.")
        hq_id, created = existing, False
    else:
        etype = payload.get("entity_type") or suggestion["suggested_entity_type"]
        raw = payload.get("details") if payload.get("details") is not None else (suggestion.get("details") or {})
        description = payload.get("description") if payload.get("description") is not None else ev.get("description")
        hq_id = extraction_module._create_entity(
            cur, user, etype, payload.get("name") or suggestion["suggested_name"] or "",
            description=description, raw_details=raw)
        if ev.get("is_active") is False:
            cur.execute("UPDATE entities SET is_active = FALSE, archived_reason = %s WHERE id = %s",
                        ("Archived on the field server", hq_id))
        created = True
    _map(cur, origin, ev.get("field_entity_id"), hq_id, suggestion.get("field_import_id"), user)
    cur.execute("UPDATE extraction_suggestions SET status = 'accepted', resolved_entity_id = %s, "
                "reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                (hq_id, user["id"], suggestion["id"]))
    audit.record("extraction.accept", user=user, object_type="extraction_suggestion",
                 object_id=suggestion["id"], object_label=suggestion.get("suggested_name"),
                 detail={"accepted_as": "entity" if created else "existing_entity",
                         "entity_id": hq_id, "via": "field_sync", "origin": ev.get("origin_name")})
    return {"id": suggestion["id"], "status": "accepted", "resolved_entity_id": hq_id,
            "created": created}


def adopt_created_end(cur, suggestion: dict, side: str, hq_id: str, user: dict) -> None:
    """The reviewer made one end of a field link from the link card itself.
    That record's own proposal from the same package is now answered: map it
    and close it, or accepting it later would make a second copy."""
    ev = suggestion.get("evidence") or {}
    origin, field_id = ev.get("origin_id"), ev.get(f"field_{side}_id")
    if not origin or not field_id:
        return
    _map(cur, origin, field_id, hq_id, suggestion.get("field_import_id"), user)
    cur.execute(
        "UPDATE extraction_suggestions SET status = 'accepted', resolved_entity_id = %s, "
        "       reviewed_by = %s, reviewed_at = now() "
        " WHERE source = 'field' AND status = 'pending' AND suggestion_type = 'entity' "
        "   AND evidence->>'origin_id' = %s AND evidence->>'field_entity_id' = %s",
        (hq_id, user["id"], origin, field_id))


def link_promoted_report(cur, submission_id: int, report_id: str) -> list[str]:
    """A field-server report promoted from the inbox gets back the links it had
    there, to every record HQ now knows by that name. Ones not yet accepted
    are still listed in its text."""
    cur.execute("SELECT s.link_entities, i.origin_id FROM field_submissions s "
                "  LEFT JOIN field_imports i ON i.id = s.field_import_id WHERE s.id = %s",
                (submission_id,))
    row = cur.fetchone()
    if not row or not row[0] or not row[1]:
        return []
    linked = []
    for ent in row[0]:
        hq = _resolve(cur, row[1], ent.get("id"))
        if hq:
            cur.execute("INSERT INTO report_entities (report_id, entity_id) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING", (report_id, hq))
            linked.append(hq)
    return linked
