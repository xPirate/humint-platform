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

ONLINE

With internet (pre-deployment Wi-Fi), the box can also look for a newer
build itself: it reads the repository's GitHub releases (deploy/publish-
release.sh makes them: the same signed bundle, and the change log as the
release notes), shows what changed since the installed build, and on an
admin's say-so downloads the bundle into the same inbox. The download is
trusted no more than an upload: root checks its signature against this
box's key before anything changes, so a GitHub account or a network in
between can at worst offer a bundle that is refused.
"""
import json
import os
import re
import shutil
import threading
import time

import requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

import audit
import auth

router = APIRouter(prefix="/api/admin/field-update", tags=["admin"])

INBOX = os.environ.get("UPDATE_INBOX", "")
STATUS_FILE = os.environ.get("UPDATE_STATUS_FILE", "/run/humint/update.json")
BUILD_FILE = os.environ.get("BUILD_FILE", "/opt/humint-platform/BUILD.json")
MAX_MB = int(os.environ.get("MAX_UPDATE_MB", "600"))
# Online: where the releases are, and what this box is (as humint-update.sh reads it).
UPDATE_REPO = os.environ.get("UPDATE_REPO", "xPirate/humint-platform").strip()
GITHUB_API = os.environ.get("UPDATE_GITHUB_API", "https://api.github.com").rstrip("/")
# Downloads are taken only from this repository's releases on this host.
DOWNLOAD_BASE = os.environ.get("UPDATE_DOWNLOAD_BASE", "https://github.com").rstrip("/")
PLATFORM_FILE = os.environ.get("PLATFORM_FILE", "/opt/humint/platform")
CHECK_CACHE_SECONDS = 600
# humint-update-<build>-<commit>[-x86].tar; "-dirty" builds are never offered.
ASSET_RE = re.compile(r"^humint-update-(\d+)-([0-9a-f]{6,40})(-x86)?\.tar$")


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@router.get("")
def status(user: dict = Depends(auth.require_admin)):
    return {"managed": bool(INBOX), "installed": _read(BUILD_FILE), "last": _read(STATUS_FILE),
            "pending": bool(INBOX) and os.path.exists(INBOX), "download": dict(_download),
            "repo": UPDATE_REPO}


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


# ---- online ------------------------------------------------------------------------------

_cache = {"at": 0.0, "releases": None, "error": None}
_download = {"state": "idle", "build": None, "done": 0, "size": 0, "message": ""}
_lock = threading.Lock()


def platform() -> str:
    try:
        with open(PLATFORM_FILE) as fh:
            return "x86" if fh.read().strip() == "x86" else "pi"
    except OSError:
        return "pi"


def installed_build() -> int:
    b = _read(BUILD_FILE) or {}
    try:
        return int(b.get("build") or 0)
    except (TypeError, ValueError):
        return 0


def _releases(refresh: bool) -> list:
    """The repository's published releases (not drafts or pre-releases), each
    with the bundle for this kind of machine, if it carries one."""
    now = time.time()
    if not refresh and _cache["releases"] is not None and now - _cache["at"] < CHECK_CACHE_SECONDS:
        return _cache["releases"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", UPDATE_REPO):
        raise HTTPException(status_code=500, detail="UPDATE_REPO is not owner/name")
    try:
        r = requests.get(f"{GITHUB_API}/repos/{UPDATE_REPO}/releases", params={"per_page": 30}, timeout=20,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "humint-platform-updater"})
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="GitHub could not be reached — is this machine online? "
                                                    f"({type(exc).__name__})")
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise HTTPException(status_code=429, detail="GitHub's limit for unsigned-in checks (60 an hour) was "
                                                    "reached on this network. Try again in a while.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub answered {r.status_code}")
    plat = platform()
    out = []
    for rel in r.json():
        if rel.get("draft") or rel.get("prerelease"):
            continue
        for a in rel.get("assets") or []:
            m = ASSET_RE.match(a.get("name") or "")
            if not m or (m.group(3) == "-x86") != (plat == "x86"):
                continue
            url = a.get("browser_download_url") or ""
            # Only from this repository's own releases, whatever the listing says.
            if not url.startswith(f"{DOWNLOAD_BASE}/{UPDATE_REPO}/releases/download/"):
                continue
            out.append({"build": int(m.group(1)), "commit": m.group(2), "asset": a["name"], "url": url,
                        "size": int(a.get("size") or 0), "tag": rel.get("tag_name"), "name": rel.get("name"),
                        "published_at": rel.get("published_at"), "notes": (rel.get("body") or "").strip(),
                        "page": rel.get("html_url")})
            break
    out.sort(key=lambda x: x["build"], reverse=True)
    _cache.update(at=now, releases=out, error=None)
    return out


@router.get("/online")
def check_online(refresh: bool = False, user: dict = Depends(auth.require_admin)):
    """What is newer than the installed build, newest first, each with its
    release notes — together, the change log since this box was updated."""
    rels = _releases(refresh)
    have = installed_build()
    newer = [r for r in rels if r["build"] > have]
    return {"repo": UPDATE_REPO, "platform": platform(), "installed_build": have,
            "managed": bool(INBOX), "latest": rels[0] if rels else None,
            "available": newer[0] if newer else None,
            "changes": [{k: r[k] for k in ("build", "commit", "name", "published_at", "notes", "page")} for r in newer],
            "checked_at": _cache["at"], "download": dict(_download)}


class OnlineInstall(BaseModel):
    build: int


def _fetch(rel: dict, user: dict):
    tmp = INBOX + ".part"
    try:
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        with requests.get(rel["url"], stream=True, timeout=60,
                          headers={"User-Agent": "humint-platform-updater"}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"GitHub answered {r.status_code}")
            done = 0
            with open(tmp, "wb") as out:
                for chunk in r.iter_content(1 << 20):
                    done += len(chunk)
                    if done > MAX_MB * 1024 * 1024:
                        raise RuntimeError(f"larger than {MAX_MB} MB")
                    out.write(chunk)
                    _download["done"] = done
        if rel["size"] and done != rel["size"]:
            raise RuntimeError("the download was cut short")
        if os.path.exists(INBOX):
            raise RuntimeError("another update is already waiting to be applied")
        # The rename is what root's watcher sees: never half a file.
        os.replace(tmp, INBOX)
        _download.update(state="queued", message="Downloaded. Checking its signature and applying it — the console "
                                                  "restarts on the new version in a minute or two.")
        audit.record("field_update.online", user=user, object_type="system", object_label=rel["asset"],
                     detail={"build": rel["build"], "commit": rel["commit"], "size_bytes": done, "repo": UPDATE_REPO})
    except Exception as exc:  # noqa: BLE001 - reported on the page
        _download.update(state="failed", message=f"The download failed: {exc}")
        try:
            os.unlink(tmp)
        except OSError:
            pass


@router.post("/online", status_code=202)
def install_online(payload: OnlineInstall, user: dict = Depends(auth.require_admin)):
    """Download the bundle of a newer release into the inbox; root checks and
    applies it exactly as an uploaded one."""
    if not INBOX:
        raise HTTPException(status_code=404, detail="This console is not a field server")
    rel = next((r for r in _releases(False) if r["build"] == payload.build), None)
    if not rel:
        rel = next((r for r in _releases(True) if r["build"] == payload.build), None)
    if not rel:
        raise HTTPException(status_code=404, detail="No release of that build for this kind of machine")
    if rel["build"] <= installed_build():
        raise HTTPException(status_code=409, detail="That build is not newer than the one installed")
    if rel["size"] > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Larger than {MAX_MB} MB")
    with _lock:
        if _download["state"] == "downloading" or os.path.exists(INBOX):
            raise HTTPException(status_code=409, detail="An update is already on its way")
        _download.update(state="downloading", build=rel["build"], done=0, size=rel["size"],
                         message=f"Downloading build {rel['build']}…")
    threading.Thread(target=_fetch, args=(rel, user), name="update-download", daemon=True).start()
    return {"queued": True, "build": rel["build"], "message": _download["message"]}
