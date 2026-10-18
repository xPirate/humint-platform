"""Updating a field server through the console: an admin uploads a signed
bundle (deploy/pi/make-update.sh) and the box applies it.

This process (the API, running as humintd) only puts the file where root's
humint-update-inbox unit is watching. Everything that matters happens there:
the signature is checked against the key the image was built with, the
database is backed up, and a failed update is rolled back. An upload that is
not signed by this box's builder is refused there, not here — so nothing an
admin uploads is trusted by virtue of who uploaded it.

On the Docker deployment UPDATE_INBOX is unset and none of this is offered:
that is updated with git pull and docker compose.
"""
import json
import os
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import audit
import auth

router = APIRouter(prefix="/api/admin/field-update", tags=["admin"])

INBOX = os.environ.get("UPDATE_INBOX", "")
STATUS_FILE = os.environ.get("UPDATE_STATUS_FILE", "/run/humint/update.json")
BUILD_FILE = os.environ.get("BUILD_FILE", "/opt/humint-platform/BUILD.json")
MAX_MB = int(os.environ.get("MAX_UPDATE_MB", "600"))


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@router.get("")
def status(user: dict = Depends(auth.require_admin)):
    return {"managed": bool(INBOX), "installed": _read(BUILD_FILE), "last": _read(STATUS_FILE),
            "pending": bool(INBOX) and os.path.exists(INBOX)}


@router.post("", status_code=202)
def upload(file: UploadFile = File(...), user: dict = Depends(auth.require_admin)):
    if not INBOX:
        raise HTTPException(status_code=404, detail="This console is not a field server")
    if not (file.filename or "").endswith(".tar"):
        raise HTTPException(status_code=400, detail="An update bundle is a humint-update-….tar file")
    if os.path.exists(INBOX):
        raise HTTPException(status_code=409, detail="An update is already waiting to be applied")
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    tmp = INBOX + ".part"
    size = 0
    with open(tmp, "wb") as out:
        while True:
            chunk = file.file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_MB * 1024 * 1024:
                out.close()
                os.unlink(tmp)
                raise HTTPException(status_code=413, detail=f"Larger than {MAX_MB} MB")
            out.write(chunk)
    # The rename is what the watcher sees: it never picks up half a file.
    os.replace(tmp, INBOX)
    audit.record("field_update.upload", user=user, object_type="system", object_label=file.filename,
                 detail={"size_bytes": size})
    return {"queued": True, "message": "Checking and applying it. The console restarts on the new version "
                                       "in a minute or two; if it does not come back, it is put back as it was."}
