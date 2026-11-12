"""Outside events: what open sources say is happening inside an area of
responsibility (a zone marked "pull outside events").

GDELT
    The GDELT Project codes the world's news into events — who did what to
    whom, where — and publishes them as a small file every 15 minutes
    (http://data.gdeltproject.org/gdeltv2/, listed in lastupdate.txt). This
    reads those files, keeps the events placed inside a marked zone, and
    stores them. No account. Its terms: free for any use; cite GDELT and link
    to it (every screen showing these does).

    Rates. GDELT publishes every 15 minutes, so checking more often finds
    nothing new: 15 minutes is the floor on the check interval. Its API asks
    for no more than one request every five seconds; this applies the same
    spacing to every request made to GDELT, files included. Both floors are
    CHECK constraints in the database as well as limits in the API, so no
    setting gets under them. When the server has been offline it fills in up
    to the backfill window (default a day: 96 files, 8 minutes at 5 s).

    Noise. GDELT is machine-coded from news: one story becomes several events,
    and a place can be guessed wrong. Hence the filters (event types, a
    minimum number of sources, city-level places only) and hence these never
    enter the case file by themselves.

ACLED
    Hand-coded political violence and protest events, with a myACLED account
    at a level that includes API access. OAuth: the password is used only to
    get a token (24 h). One query per marked zone, by its bounding box and a
    date range, then checked against the zone's real shape here.

Everything runs on a thread of its own: a catch-up is minutes of
deliberately spaced requests, and the main loop's jobs (a document waiting
for extraction) should not wait behind it.
"""
import csv
import hashlib
import io
import os
import threading
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

from cameo import CAMEO
from db import db_cursor
from zone_geo import zone_contains

ENABLED = os.environ.get("OUTSIDE_EVENTS_ENABLED", "true").lower() not in ("0", "false", "no")
GDELT_BASE = os.environ.get("GDELT_BASE", "http://data.gdeltproject.org/gdeltv2").rstrip("/")
ACLED_BASE = os.environ.get("ACLED_BASE", "https://acleddata.com").rstrip("/")
USER_AGENT = os.environ.get(
    "OUTSIDE_EVENTS_USER_AGENT",
    "humint-platform outside-events (+https://github.com/xPirate/humint-platform)")
# The floors, as in db/init.sql. Repeated here so a hand-edited database row
# still cannot make this go faster.
GDELT_MIN_INTERVAL_MIN = 15
GDELT_MIN_SPACING_S = 5.0
ACLED_MIN_INTERVAL_MIN = 60
ACLED_MIN_SPACING_S = 1.0
LOOP_SECONDS = float(os.environ.get("OUTSIDE_EVENTS_LOOP_SECONDS", "30"))
ACLED_MAX_PAGES = 20

# ---- CAMEO, the coding GDELT uses ---------------------------------------------------
# Labels from GDELT's own code table (cameo.py): the event's own code first
# ("Kill by physical assault"), then its base code, then its root category.
CAMEO_ROOT = {code: label for code, label in CAMEO.items() if len(code) == 2}


def cameo_label(code: str, base: str, root: str) -> str:
    return CAMEO.get(code) or CAMEO.get(base) or CAMEO.get(root) or f"CAMEO {code}"


GEO_PRECISION = {"1": "country", "2": "state", "3": "city", "4": "city", "5": "state"}

# GDELT 2.0 event table columns (the codebook's order, from zero).
C_ID, C_DAY = 0, 1
C_ACTOR1, C_ACTOR2 = 6, 16
C_CODE, C_BASE, C_ROOT, C_QUAD, C_GOLDSTEIN = 26, 27, 28, 29, 30
C_MENTIONS, C_SOURCES, C_ARTICLES, C_TONE = 31, 32, 33, 34
C_GEO_TYPE, C_GEO_NAME, C_LAT, C_LON = 51, 52, 56, 57
C_ADDED, C_URL = 59, 60
GDELT_COLUMNS = 61


class Spacing:
    """At least `seconds` between one request and the next to the same
    service, counted from when each was sent."""

    def __init__(self):
        self._last = 0.0

    def wait(self, seconds: float, sleep=time.sleep):
        delay = self._last + seconds - time.monotonic()
        if delay > 0:
            sleep(delay)
        self._last = time.monotonic()


_gdelt_spacing = Spacing()
_acled_spacing = Spacing()
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


# ---- settings and zones ----------------------------------------------------------------

SETTINGS_COLS = (
    "gdelt_enabled", "gdelt_interval_minutes", "gdelt_request_spacing_seconds", "gdelt_backfill_hours",
    "gdelt_root_codes", "gdelt_min_sources", "gdelt_city_only", "gdelt_last_file", "gdelt_last_poll_at",
    "acled_enabled", "acled_username", "acled_password", "acled_interval_minutes",
    "acled_request_spacing_seconds", "acled_backfill_days", "acled_token", "acled_token_expires",
    "acled_last_poll_at", "retention_days", "pull_requested_at")


def load_settings() -> dict | None:
    with db_cursor() as cur:
        cur.execute(f"SELECT {', '.join(SETTINGS_COLS)} FROM outside_event_settings WHERE id = 1")
        row = cur.fetchone()
    if not row:
        return None
    s = dict(zip(SETTINGS_COLS, row))
    s["gdelt_interval_minutes"] = max(GDELT_MIN_INTERVAL_MIN, int(s["gdelt_interval_minutes"]))
    s["gdelt_request_spacing_seconds"] = max(GDELT_MIN_SPACING_S, float(s["gdelt_request_spacing_seconds"]))
    s["acled_interval_minutes"] = max(ACLED_MIN_INTERVAL_MIN, int(s["acled_interval_minutes"]))
    s["acled_request_spacing_seconds"] = max(ACLED_MIN_SPACING_S, float(s["acled_request_spacing_seconds"]))
    s["root_codes"] = {c.strip().zfill(2) for c in (s["gdelt_root_codes"] or "").split(",") if c.strip()}
    return s


def load_zones() -> list:
    """The marked zones still running (an expired zone stops pulling)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, shape, geometry, radius_m, min_lat, min_lon, max_lat, max_lon "
            "FROM map_zones WHERE outside_events "
            "AND (valid_until IS NULL OR valid_until > now())")
        cols = ("id", "shape", "geometry", "radius_m", "min_lat", "min_lon", "max_lat", "max_lon")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def zones_for(zones: list, lat: float, lon: float) -> list:
    return [z["id"] for z in zones if zone_contains(z, lat, lon)]


def _due(last, minutes: int, requested) -> bool:
    now = datetime.now(timezone.utc)
    if requested and (last is None or requested > last):
        return True
    return last is None or now - last >= timedelta(minutes=minutes)


def _set(**values):
    sets = ", ".join(f"{k} = %s" for k in values)
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE outside_event_settings SET {sets} WHERE id = 1", list(values.values()))


INSERT_COLS = ("source", "source_id", "occurred_on", "reported_at", "title", "category", "code",
               "actor1", "actor2", "place", "lat", "lon", "precision", "url", "sources_named",
               "num_sources", "num_articles", "tone", "goldstein", "fatalities", "notes", "zone_ids")


def store(events: list) -> int:
    """New ones only: an event already here (from an earlier file, or seen
    again) keeps its status — a dismissed event never comes back as new."""
    if not events:
        return 0
    added = 0
    with db_cursor(commit=True) as cur:
        for e in events:
            cur.execute(
                f"INSERT INTO outside_events ({', '.join(INSERT_COLS)}) "
                f"VALUES ({', '.join(['%s'] * len(INSERT_COLS))}) "
                "ON CONFLICT (source, source_id) DO NOTHING",
                [e.get(c) for c in INSERT_COLS])
            added += cur.rowcount
    return added


# ---- GDELT ------------------------------------------------------------------------------

def _name(s: str) -> str | None:
    s = (s or "").strip()
    return " ".join(w.capitalize() for w in s.split()) if s else None


def gdelt_event(row: list, settings: dict, zones: list) -> dict | None:
    """One row of a GDELT export file, as an outside event — or None when it
    is outside every marked zone or filtered out."""
    if len(row) < GDELT_COLUMNS:
        return None
    try:
        lat, lon = float(row[C_LAT]), float(row[C_LON])
    except ValueError:
        return None
    geo_type = row[C_GEO_TYPE]
    if settings["gdelt_city_only"] and geo_type not in ("3", "4"):
        return None
    root = row[C_ROOT].zfill(2)
    if settings["root_codes"] and root not in settings["root_codes"]:
        return None
    try:
        sources = int(row[C_SOURCES] or 0)
    except ValueError:
        sources = 0
    if sources < int(settings["gdelt_min_sources"] or 1):
        return None
    inside = zones_for(zones, lat, lon)
    if not inside:
        return None

    label = cameo_label(row[C_CODE], row[C_BASE], root)
    a1, a2 = _name(row[C_ACTOR1]), _name(row[C_ACTOR2])
    title = label + (f": {a1}" if a1 else "") + (f" → {a2}" if a2 else "")
    try:
        occurred = datetime.strptime(row[C_DAY], "%Y%m%d").date()
    except ValueError:
        occurred = None
    try:
        reported = datetime.strptime(row[C_ADDED], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        reported = None

    def num(i, kind=float):
        try:
            return kind(row[i])
        except (ValueError, TypeError):
            return None

    return {
        "source": "gdelt", "source_id": row[C_ID], "occurred_on": occurred, "reported_at": reported,
        "title": title[:300], "category": CAMEO_ROOT.get(root), "code": row[C_CODE],
        "actor1": a1, "actor2": a2, "place": row[C_GEO_NAME] or None, "lat": lat, "lon": lon,
        "precision": GEO_PRECISION.get(geo_type), "url": row[C_URL] or None, "sources_named": None,
        "num_sources": sources, "num_articles": num(C_ARTICLES, int), "tone": num(C_TONE),
        "goldstein": num(C_GOLDSTEIN), "fatalities": None, "notes": None, "zone_ids": inside,
    }


def gdelt_rows(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def _get(url: str, spacing: Spacing, seconds: float, **kw):
    spacing.wait(seconds)
    return _session.get(url, timeout=60, **kw)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def files_to_read(latest: str, last_read: str | None, backfill_hours: int) -> list:
    """The 15-minute files between the last one read and the newest, never
    reaching back further than the backfill window."""
    newest = _parse_stamp(latest)
    # The window is that many hours of files, ending with the newest: a day
    # is 96 files.
    floor = newest - timedelta(hours=backfill_hours) + timedelta(minutes=15)
    start = _parse_stamp(last_read) + timedelta(minutes=15) if last_read else floor
    start = max(start, floor)
    # On the 15-minute grid.
    start = start.replace(minute=start.minute - start.minute % 15, second=0)
    if backfill_hours == 0 and not last_read:
        start = newest
    out, t = [], start
    while t <= newest:
        out.append(_stamp(t))
        t += timedelta(minutes=15)
    return out


def pull_gdelt(settings: dict, zones: list) -> int:
    spacing = settings["gdelt_request_spacing_seconds"]
    r = _get(f"{GDELT_BASE}/lastupdate.txt", _gdelt_spacing, spacing)
    r.raise_for_status()
    latest, latest_md5 = None, None
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
            latest = os.path.basename(parts[2]).split(".")[0]
            latest_md5 = parts[1]
    if not latest:
        raise RuntimeError("GDELT's lastupdate.txt named no event file")
    added = 0
    for stamp in files_to_read(latest, settings["gdelt_last_file"], int(settings["gdelt_backfill_hours"])):
        r = _get(f"{GDELT_BASE}/{stamp}.export.CSV.zip", _gdelt_spacing, spacing)
        if r.status_code == 404:          # GDELT skips the odd interval
            _set(gdelt_last_file=stamp)
            continue
        r.raise_for_status()
        if stamp == latest and latest_md5 and hashlib.md5(r.content).hexdigest() != latest_md5:
            raise RuntimeError(f"GDELT file {stamp} did not match its checksum")
        events = [e for e in (gdelt_event(row, settings, zones) for row in gdelt_rows(r.content)) if e]
        added += store(events)
        _set(gdelt_last_file=stamp)       # progress kept file by file
    return added


# ---- ACLED ------------------------------------------------------------------------------

def _acled_token(settings: dict) -> str:
    tok, exp = settings.get("acled_token"), settings.get("acled_token_expires")
    if tok and exp and exp - datetime.now(timezone.utc) > timedelta(minutes=5):
        return tok
    if not settings.get("acled_username") or not settings.get("acled_password"):
        raise RuntimeError("ACLED needs the myACLED email and password (Admin → Outside events)")
    _acled_spacing.wait(settings["acled_request_spacing_seconds"])
    r = _session.post(f"{ACLED_BASE}/oauth/token", timeout=60, data={
        "username": settings["acled_username"], "password": settings["acled_password"],
        "grant_type": "password", "client_id": "acled", "scope": "authenticated"})
    if r.status_code in (400, 401, 403):
        raise RuntimeError("ACLED refused the sign-in (check the email and password, "
                           "and that the account's access level includes the API)")
    r.raise_for_status()
    body = r.json()
    tok = body["access_token"]
    exp = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 86400)))
    _set(acled_token=tok, acled_token_expires=exp)
    settings["acled_token"], settings["acled_token_expires"] = tok, exp
    return tok


def acled_event(rec: dict, zones: list) -> dict | None:
    try:
        lat, lon = float(rec["latitude"]), float(rec["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    inside = zones_for(zones, lat, lon)
    if not inside or not rec.get("event_id_cnty"):
        return None
    kind, sub = rec.get("event_type") or "Event", rec.get("sub_event_type") or ""
    a1, a2 = rec.get("actor1") or None, rec.get("actor2") or None
    title = (sub or kind) + (f": {a1}" if a1 else "") + (f" → {a2}" if a2 else "")
    try:
        occurred = date.fromisoformat(rec.get("event_date", "")[:10])
    except ValueError:
        occurred = None
    try:
        reported = datetime.fromtimestamp(int(rec.get("timestamp")), tz=timezone.utc)
    except (TypeError, ValueError):
        reported = None
    try:
        deaths = int(rec.get("fatalities"))
    except (TypeError, ValueError):
        deaths = None
    place = ", ".join(p for p in (rec.get("location"), rec.get("admin1"), rec.get("country")) if p)
    return {
        "source": "acled", "source_id": str(rec["event_id_cnty"]), "occurred_on": occurred,
        "reported_at": reported, "title": title[:300], "category": kind, "code": sub or None,
        "actor1": a1, "actor2": a2, "place": place or None, "lat": lat, "lon": lon,
        "precision": {"1": "exact", "2": "near", "3": "region"}.get(str(rec.get("geo_precision")), None),
        "url": None, "sources_named": rec.get("source") or None, "num_sources": None,
        "num_articles": None, "tone": None, "goldstein": None, "fatalities": deaths,
        "notes": rec.get("notes") or None, "zone_ids": inside,
    }


def pull_acled(settings: dict, zones: list) -> int:
    today = date.today()
    if settings.get("acled_last_poll_at"):
        # ACLED adds events late and revises them: look back two weeks past
        # the last pull as well (already-stored ones are skipped).
        since = settings["acled_last_poll_at"].date() - timedelta(days=14)
    else:
        since = today - timedelta(days=int(settings["acled_backfill_days"]))
    added = 0
    for z in zones:
        cursor = "0"
        for _ in range(ACLED_MAX_PAGES):
            params = {
                "_format": "json", "limit": 1000, "cursor": cursor,
                "latitude": f"{z['min_lat']}|{z['max_lat']}", "latitude_where": "BETWEEN",
                "longitude": f"{z['min_lon']}|{z['max_lon']}", "longitude_where": "BETWEEN",
                "event_date": f"{since.isoformat()}|{today.isoformat()}", "event_date_where": "BETWEEN",
            }
            for attempt in (1, 2):
                tok = _acled_token(settings)
                _acled_spacing.wait(settings["acled_request_spacing_seconds"])
                r = _session.get(f"{ACLED_BASE}/api/acled/read", params=params, timeout=120,
                                 headers={"Authorization": f"Bearer {tok}"})
                if r.status_code == 401 and attempt == 1:
                    settings["acled_token"] = None           # expired early: sign in again
                    continue
                break
            if r.status_code in (401, 403):
                raise RuntimeError("ACLED refused the request: this account's access level "
                                   "may not include the API, or this area")
            r.raise_for_status()
            body = r.json()
            rows = body.get("data") or []
            # The query is by bounding box; the zone's real shape decides.
            added += store([e for e in (acled_event(rec, [z]) for rec in rows) if e])
            cursor = body.get("next_cursor")
            if not rows or cursor in (None, "", 0, "0"):
                break
            cursor = str(cursor)
    return added


# ---- retention, and the loop ---------------------------------------------------------------

def prune(retention_days: int) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM outside_events WHERE status <> 'sent' "
            "AND COALESCE(occurred_on, created_at::date) < (now() - make_interval(days => %s))::date",
            (int(retention_days),))
        return cur.rowcount


def run_once(now_prune: bool = False) -> dict:
    """One pass: each source if it is on, due, and there is a marked zone.
    Returns what it did, for the log and the tests."""
    done = {}
    settings = load_settings()
    if not settings:
        return done
    zones = load_zones()
    requested = settings.get("pull_requested_at")
    if zones and settings["gdelt_enabled"] and _due(settings["gdelt_last_poll_at"],
                                                     settings["gdelt_interval_minutes"], requested):
        try:
            done["gdelt"] = pull_gdelt(settings, zones)
            _set(gdelt_last_poll_at=datetime.now(timezone.utc), gdelt_last_error=None)
        except Exception as exc:          # recorded for the settings page; tried again next interval
            done["gdelt_error"] = str(exc)
            _set(gdelt_last_poll_at=datetime.now(timezone.utc), gdelt_last_error=str(exc)[:1000])
    if zones and settings["acled_enabled"] and _due(settings["acled_last_poll_at"],
                                                     settings["acled_interval_minutes"], requested):
        try:
            done["acled"] = pull_acled(settings, zones)
            _set(acled_last_poll_at=datetime.now(timezone.utc), acled_last_error=None)
        except Exception as exc:
            done["acled_error"] = str(exc)
            _set(acled_last_poll_at=datetime.now(timezone.utc), acled_last_error=str(exc)[:1000])
    if now_prune:
        done["pruned"] = prune(settings["retention_days"])
    for k, v in done.items():
        if v:
            print(f"[worker] outside events: {k} = {v}", flush=True)
    return done


def _loop():
    last_prune = 0.0
    while True:
        try:
            hourly = time.monotonic() - last_prune > 3600
            run_once(now_prune=hourly)
            if hourly:
                last_prune = time.monotonic()
        except Exception as exc:
            print(f"[worker] outside events: {exc}", flush=True)
        time.sleep(LOOP_SECONDS)


def start_outside_events_thread() -> None:
    if not ENABLED:
        print("[worker] outside events disabled (OUTSIDE_EVENTS_ENABLED=false)", flush=True)
        return
    threading.Thread(target=_loop, name="outside-events", daemon=True).start()
    print("[worker] outside events thread started (GDELT floor: 15 min checks, 5 s between requests)",
          flush=True)
