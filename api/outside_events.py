"""Outside events: open-source events (GDELT, ACLED) inside the zones marked
as areas of responsibility — the page, the map layer, and the settings.

The worker pulls them (worker/outside_events.py). Here they are read,
dismissed, and — the only way any of it reaches the case file — sent to
Documents by an analyst, exactly as a feed item is (api/feeds.py): the
linked article is fetched, and extraction and review follow as for any
document.

The settings carry the rates. Their floors come from the sources' own terms
and are enforced three times over (here, in the database's CHECKs, and in
the worker): GDELT publishes every 15 minutes and asks for at most one
request every 5 seconds.
"""
from datetime import datetime, timezone
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import audit
import auth
from db import db_cursor
from feeds import UPLOAD_DIR, fetch_article
import reader

router = APIRouter(prefix="/api/outside-events", tags=["outside-events"])
admin_router = APIRouter(prefix="/api/admin/outside-events", tags=["outside-events"])

SOURCES = ("gdelt", "acled")
STATUSES = ("new", "read", "dismissed", "sent")
# What each source asks credit as, shown wherever its events are.
CREDIT = {
    "gdelt": {"name": "GDELT Project", "url": "https://www.gdeltproject.org/"},
    "acled": {"name": "ACLED", "url": "https://acleddata.com/"},
}

# The limits, for the settings screens and for checking a change. The minimums
# are the sources' own terms (see the module docstring).
LIMITS = {
    "gdelt_interval_minutes": (15, 10080),
    "gdelt_request_spacing_seconds": (5, 3600),
    "gdelt_backfill_hours": (0, 168),
    "gdelt_min_sources": (1, 100),
    "acled_interval_minutes": (60, 10080),
    "acled_request_spacing_seconds": (1, 3600),
    "acled_backfill_days": (1, 365),
    "retention_days": (1, 3650),
    "article_spacing_seconds": (1, 600),
    "articles_per_pass": (1, 1000),
    "dedupe_model_threshold": (0.5, 0.99),
    "triage_per_pass": (1, 500),
    "triage_min_severity": (1, 5),
    "triage_examples": (0, 30),
}
# The model's triage (worker/outside_triage.py has the same keys, with the
# hints the model is shown; tests/test_outside_triage.py checks they match).
TRIAGE_CATEGORIES = {
    "protest": "Protest or demonstration",
    "unrest": "Civil unrest or riot",
    "violent_crime": "Violent crime",
    "police": "Arrest or police action",
    "attack": "Attack or armed violence",
    "threat": "Threat or extremism",
    "disaster": "Disaster or emergency",
    "infrastructure": "Infrastructure or outage",
    "government": "Government or political",
    "other": "Other",
}
SEVERITY_LABELS = {1: "routine", 2: "minor", 3: "notable", 4: "significant", 5: "critical"}
# Filtered: the model (or a person) said it is not an event, not in the area,
# or below the severity shown. %s is the minimum severity.
FILTERED_SQL = ("(e.triaged_at IS NOT NULL AND (e.triage_is_event IS FALSE OR e.triage_in_area IS FALSE "
                "OR e.triage_severity < %s))")
# The CAMEO root categories, for choosing which GDELT event types to keep.
ROOT_CODES = [
    ("01", "Public statement"), ("02", "Appeal"), ("03", "Intent to cooperate"), ("04", "Consult"),
    ("05", "Diplomatic cooperation"), ("06", "Material cooperation"), ("07", "Provide aid"),
    ("08", "Yield"), ("09", "Investigate"), ("10", "Demand"), ("11", "Disapprove"), ("12", "Reject"),
    ("13", "Threaten"), ("14", "Protest"), ("15", "Show of force"), ("16", "Reduce relations"),
    ("17", "Coerce (incl. arrests)"), ("18", "Assault"), ("19", "Fight"), ("20", "Mass violence"),
]

EVENT_COLS = ("id", "source", "source_id", "occurred_on", "reported_at", "title", "category", "code",
              "actor1", "actor2", "place", "lat", "lon", "precision", "url", "sources_named",
              "num_sources", "num_articles", "tone", "goldstein", "fatalities", "notes", "zone_ids",
              "status", "attachment_id", "sent_at", "created_at", "dup_of", "dup_reason",
              "triage_is_event", "triage_in_area", "triage_category", "triage_severity", "triage_summary",
              "triage_reason", "triage_by", "triage_model", "triaged_at", "triage_error")
TRIAGE_COLS = EVENT_COLS[EVENT_COLS.index("triage_is_event"):]
# Shown with each event: its article's headline and site, when it has been read.
ARTICLE_JOIN = "LEFT JOIN outside_articles a ON a.url = e.url"
ARTICLE_COLS = ("a.title", "a.site", "a.fetched_at IS NOT NULL AND a.body IS NOT NULL")
REASONS = {"same_article": "the same article", "same_place_type_day": "same kind of event, same place, same day",
           "same_headline": "near-identical headline", "model": "the model judged it the same story"}


def triage_config(cur) -> dict:
    """Whether the model's triage is on, and the least severity shown."""
    try:
        cur.execute("SELECT triage_enabled, triage_min_severity FROM outside_event_settings WHERE id = 1")
        r = cur.fetchone()
    except Exception:
        r = None
    return {"enabled": bool(r and r[0]), "min_severity": int(r[1]) if r and r[1] else 1}


def _not_filtered(cfg: dict) -> tuple[str, list]:
    """A WHERE fragment that leaves out what the triage filtered, when it is on."""
    if not cfg["enabled"]:
        return "", []
    return f"NOT {FILTERED_SQL}", [cfg["min_severity"]]


def _event(row, cfg: dict | None = None) -> dict:
    e = dict(zip(EVENT_COLS, row[:len(EVENT_COLS)]))
    t = {k[len("triage_"):] if k.startswith("triage_") else k: e.pop(k) for k in TRIAGE_COLS}
    if t["triaged_at"] is not None:
        sev = t["severity"]
        e["triage"] = {"is_event": t["is_event"], "in_area": t["in_area"], "category": t["category"],
                       "category_label": TRIAGE_CATEGORIES.get(t["category"] or "", t["category"]),
                       "severity": sev, "severity_label": SEVERITY_LABELS.get(sev),
                       "summary": t["summary"], "reason": t["reason"], "by": t["by"], "model": t["model"],
                       "at": t["triaged_at"].isoformat()}
    else:
        e["triage"] = None
        e["triage_error"] = t["error"]
    cfg = cfg or {"enabled": False, "min_severity": 1}
    tr = e["triage"]
    e["filtered"] = bool(cfg["enabled"] and tr and (tr["is_event"] is False or tr["in_area"] is False
                                                    or (tr["severity"] or 5) < cfg["min_severity"]))
    extra = row[len(EVENT_COLS):]
    if extra:
        e["headline"], e["site"], e["article_ready"] = extra[0], extra[1], bool(extra[2])
        if len(extra) > 3:
            e["similar"] = extra[3] or 0
    if e.get("dup_reason"):
        e["dup_reason_text"] = REASONS.get(e["dup_reason"], e["dup_reason"])
    for k in ("occurred_on", "reported_at", "sent_at", "created_at"):
        if e.get(k) is not None:
            e[k] = e[k].isoformat()
    e["credit"] = CREDIT.get(e["source"])
    return e


def _filters(zone_id, source, status, days, q):
    where, params = [], []
    if zone_id is not None:
        where.append("%s = ANY(e.zone_ids)")
        params.append(zone_id)
    if source:
        if source not in SOURCES:
            raise HTTPException(status_code=400, detail="Unknown source.")
        where.append("e.source = %s")
        params.append(source)
    if status and status != "all":
        if status == "unread":
            where.append("e.status IN ('new')")
        elif status == "open":
            where.append("e.status IN ('new', 'read')")
        elif status in STATUSES:
            where.append("e.status = %s")
            params.append(status)
        else:
            raise HTTPException(status_code=400, detail="Unknown status.")
    if days:
        where.append("COALESCE(e.occurred_on, e.created_at::date) >= (now() - make_interval(days => %s))::date")
        params.append(int(days))
    if q:
        where.append("(e.title ILIKE %s OR e.place ILIKE %s OR e.notes ILIKE %s)")
        params += [f"%{q}%"] * 3
    return (" WHERE " + " AND ".join(where)) if where else "", params


@router.get("")
def list_events(zone_id: Optional[int] = Query(default=None),
                source: Optional[str] = Query(default=None),
                status: str = Query(default="open"),
                days: Optional[int] = Query(default=None, ge=1, le=3650),
                q: Optional[str] = Query(default=None, max_length=200),
                limit: int = Query(default=100, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                grouped: bool = True,
                view: str = Query(default="main"),
                category: Optional[str] = Query(default=None),
                sort: str = Query(default="date"),
                user: dict = Depends(auth.require_user)):
    """Grouped (the default): one entry per incident, its duplicates counted
    under it (`similar`) and listed by /{id}/similar.

    With the model's triage on, `view` is "main" (what it kept, and what it
    has not judged yet), "filtered" (what it set aside, with its reason) or
    "all". `category` is one of the triage categories; `sort` is "date" or
    "severity"."""
    if view not in ("main", "filtered", "all"):
        raise HTTPException(status_code=400, detail="Unknown view.")
    if category and category not in TRIAGE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category.")
    if sort not in ("date", "severity"):
        raise HTTPException(status_code=400, detail="Unknown order.")
    clause, params = _filters(zone_id, source, status, days, q)
    where = [clause[7:]] if clause else []
    if grouped:
        where.append("e.dup_of IS NULL")
    if category:
        where.append("e.triage_category = %s")
        params.append(category)
    with db_cursor() as cur:
        cfg = triage_config(cur)
        base_where, base_params = list(where), list(params)
        if cfg["enabled"] and view == "main":
            where.append(f"NOT {FILTERED_SQL}")
            params.append(cfg["min_severity"])
        elif cfg["enabled"] and view == "filtered":
            where.append(FILTERED_SQL)
            params.append(cfg["min_severity"])
        sql_where = (" WHERE " + " AND ".join(where)) if where else ""
        cols = ", ".join(["e." + c for c in EVENT_COLS] + list(ARTICLE_COLS)
                         + ["(SELECT count(*) FROM outside_events d WHERE d.dup_of = e.id)"])
        order = ("COALESCE(e.triage_severity, 0) DESC, " if sort == "severity" else "") + \
            "COALESCE(e.occurred_on, e.created_at::date) DESC, e.id DESC"
        cur.execute(f"SELECT count(*) FROM outside_events e{sql_where}", params)
        total = cur.fetchone()[0]
        cur.execute(f"SELECT {cols} FROM outside_events e {ARTICLE_JOIN}{sql_where} "
                    f"ORDER BY {order} LIMIT %s OFFSET %s", [*params, limit, offset])
        items = [_event(r, cfg) for r in cur.fetchall()]
        # How many the triage set aside under the same filters, for the toggle.
        filtered_total = 0
        if cfg["enabled"]:
            fw = base_where + [FILTERED_SQL]
            cur.execute(f"SELECT count(*) FROM outside_events e WHERE {' AND '.join(fw)}",
                        [*base_params, cfg["min_severity"]])
            filtered_total = cur.fetchone()[0]
        nf, nf_params = _not_filtered(cfg)
        nf_and = f" AND {nf}" if nf else ""
        # The marked zones, for the filter and for naming each event's zones.
        cur.execute("SELECT z.id, COALESCE(ze.name, z.name), "
                    "       (SELECT count(*) FROM outside_events e WHERE z.id = ANY(e.zone_ids) AND e.status = 'new' "
                    f"          AND e.dup_of IS NULL{nf_and}) "
                    "  FROM map_zones z LEFT JOIN entities ze ON ze.id = z.entity_id "
                    " WHERE z.outside_events ORDER BY 2", nf_params)
        zones = [{"id": r[0], "name": r[1], "unread": r[2]} for r in cur.fetchall()]
        cur.execute(f"SELECT count(*) FROM outside_events e WHERE e.status = 'new' AND e.dup_of IS NULL{nf_and}",
                    nf_params)
        unread = cur.fetchone()[0]
    return {"items": items, "total": total, "zones": zones, "unread_total": unread,
            "filtered_total": filtered_total, "triage_enabled": cfg["enabled"],
            "min_severity": cfg["min_severity"],
            "categories": [{"key": k, "label": v} for k, v in TRIAGE_CATEGORIES.items()],
            "credit": CREDIT}


@router.get("/map")
def map_points(zone_id: Optional[int] = Query(default=None),
               days: int = Query(default=7, ge=1, le=3650),
               include_dismissed: bool = False,
               min_lat: Optional[float] = None, min_lon: Optional[float] = None,
               max_lat: Optional[float] = None, max_lon: Optional[float] = None,
               limit: int = Query(default=2000, ge=1, le=5000),
               user: dict = Depends(auth.require_user)):
    """Points for the map layer: the last `days`, optionally in a box."""
    clause, params = _filters(zone_id, None, "all" if include_dismissed else None, days, None)
    where = [clause[7:]] if clause else []
    if not include_dismissed:
        where.append("e.status <> 'dismissed'")
    where.append("e.dup_of IS NULL")
    with db_cursor() as cur:
        nf, nf_params = _not_filtered(triage_config(cur))
    if nf:
        where.append(nf)
        params += nf_params
    if None not in (min_lat, min_lon, max_lat, max_lon):
        where.append("e.lat BETWEEN %s AND %s AND e.lon BETWEEN %s AND %s")
        params += [min_lat, max_lat, min_lon, max_lon]
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    with db_cursor() as cur:
        cur.execute("SELECT e.id, e.source, COALESCE(e.triage_summary, e.title), "
                    "COALESCE(e.triage_category, e.category), e.occurred_on, e.lat, e.lon, e.status, e.place "
                    f"FROM outside_events e{sql_where} "
                    "ORDER BY COALESCE(e.occurred_on, e.created_at::date) DESC, e.id DESC LIMIT %s",
                    [*params, limit])
        pts = [{"id": r[0], "source": r[1], "title": r[2], "category": r[3],
                "occurred_on": r[4].isoformat() if r[4] else None, "lat": r[5], "lon": r[6],
                "status": r[7], "place": r[8]} for r in cur.fetchall()]
    return {"items": pts, "credit": CREDIT}


def _get(cur, event_id: int) -> dict:
    cols = ", ".join(["e." + c for c in EVENT_COLS] + list(ARTICLE_COLS)
                     + ["(SELECT count(*) FROM outside_events d WHERE d.dup_of = e.id)"])
    cur.execute(f"SELECT {cols} FROM outside_events e {ARTICLE_JOIN} WHERE e.id = %s", (event_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No such event.")
    return _event(row, triage_config(cur))


@router.get("/{event_id}")
def get_event(event_id: int, user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        return _get(cur, event_id)


class StatusRequest(BaseModel):
    status: str


@router.post("/{event_id}/status")
def set_status(event_id: int, payload: StatusRequest, user: dict = Depends(auth.require_user)):
    """Read, dismissed, or back to new. Sending is its own action. A dismissed
    event stays (so the next pull does not bring it back as new) until the
    retention window deletes it."""
    if payload.status not in ("new", "read", "dismissed"):
        raise HTTPException(status_code=400, detail="An event can be read, dismissed or put back.")
    with db_cursor(commit=True) as cur:
        e = _get(cur, event_id)
        if e["status"] == "sent":
            raise HTTPException(status_code=409, detail="That event is already in Documents.")
        cur.execute("UPDATE outside_events SET status = %s WHERE id = %s", (payload.status, event_id))
        # Dismissing (or putting back) an incident does the same to the
        # reports folded under it; reading one reads them all.
        cur.execute("UPDATE outside_events SET status = %s WHERE dup_of = %s AND status <> 'sent'",
                    (payload.status, event_id))
    return {"id": event_id, "status": payload.status}


@router.get("/{event_id}/similar")
def similar(event_id: int, user: dict = Depends(auth.require_user)):
    """The reports folded under an incident, and why each was matched."""
    with db_cursor() as cur:
        _get(cur, event_id)
        cols = ", ".join(["e." + c for c in EVENT_COLS] + list(ARTICLE_COLS))
        cur.execute(f"SELECT {cols} FROM outside_events e {ARTICLE_JOIN} WHERE e.dup_of = %s ORDER BY e.id",
                    (event_id,))
        return {"items": [_event(r) for r in cur.fetchall()]}


class TriageCorrection(BaseModel):
    is_event: bool = True
    in_area: bool = True
    category: Optional[str] = None
    severity: Optional[int] = Field(default=None, ge=1, le=5)


@router.post("/{event_id}/triage")
def correct_triage(event_id: int, payload: TriageCorrection, user: dict = Depends(auth.require_user)):
    """A person's call on an incident: final (the model never overwrites it),
    and kept as an example the model is shown on later ones."""
    if payload.category is not None and payload.category not in TRIAGE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category.")
    with db_cursor(commit=True) as cur:
        e = _get(cur, event_id)
        if e["dup_of"]:
            raise HTTPException(status_code=409, detail="Correct the incident this report is folded under.")
        before = e["triage"]
        category = payload.category or (before or {}).get("category") or "other"
        severity = payload.severity or (before or {}).get("severity") or 2
        verdict = {"is_event": payload.is_event, "in_area": payload.in_area,
                   "category": category, "severity": severity}
        cur.execute("UPDATE outside_events SET triage_is_event = %s, triage_in_area = %s, triage_category = %s, "
                    "triage_severity = %s, triage_by = 'analyst', triaged_at = now(), triage_error = NULL, "
                    "triage_reason = %s, triage_summary = COALESCE(triage_summary, %s) WHERE id = %s",
                    (payload.is_event, payload.in_area, category, severity,
                     f"Set by {user.get('username') or 'an analyst'}", e["title"][:300], event_id))
        cur.execute("SELECT body FROM outside_articles WHERE url = %s", (e.get("url") or "",))
        r = cur.fetchone()
        head = e.get("headline") or e["title"]
        body = ((r[0] if r else None) or e.get("notes") or "")[:200]
        model_verdict = ({k: before.get(k) for k in ("is_event", "in_area", "category", "severity")}
                         if before and before.get("by") == "model" else None)
        cur.execute("INSERT INTO outside_triage_corrections (event_id, zone_ids, text, model_verdict, verdict, "
                    "corrected_by) VALUES (%s, %s, %s, %s, %s, %s)",
                    (event_id, e["zone_ids"], (head + (" — " + body if body else ""))[:600],
                     json.dumps(model_verdict) if model_verdict else None, json.dumps(verdict), user.get("id")))
        out = _get(cur, event_id)
    audit.record("outside_event.triage", user=user, object_type="outside_events", object_id=event_id,
                 object_label=e["title"][:200], detail={"verdict": verdict, "model": model_verdict})
    return out


@router.post("/{event_id}/separate")
def separate(event_id: int, user: dict = Depends(auth.require_user)):
    """"Not the same": take a report out of the incident it was folded under,
    for good — it is never matched again."""
    with db_cursor(commit=True) as cur:
        e = _get(cur, event_id)
        if not e["dup_of"]:
            raise HTTPException(status_code=409, detail="That event is not folded under another.")
        cur.execute("UPDATE outside_events SET dup_of = NULL, dup_reason = NULL, dedupe_locked = TRUE, "
                    "status = CASE WHEN status = 'dismissed' THEN 'new' ELSE status END WHERE id = %s", (event_id,))
    audit.record("outside_event.separate", user=user, object_type="outside_events", object_id=event_id,
                 object_label=e["title"][:200], detail={"was_under": e["dup_of"], "reason": e["dup_reason"]})
    return {"id": event_id, "separated": True}


@router.get("/{event_id}/article")
def article(event_id: int, refresh: bool = False, user: dict = Depends(auth.require_user)):
    """The event's article in reader form, for the side panel. Fetched once
    by the server and kept (the worker fetches ahead when that is on); a
    failure is kept too, and tried again on request."""
    with db_cursor() as cur:
        e = _get(cur, event_id)
    url = e.get("url")
    if not url:
        return {"event": e, "article": None,
                "error": "This event has no article (ACLED names its sources instead)." if e["source"] == "acled"
                else "This event has no article.", "notes": e.get("notes")}
    with db_cursor() as cur:
        cur.execute("SELECT final_url, title, site, published, body, error, fetched_at FROM outside_articles "
                    "WHERE url = %s", (url,))
        row = cur.fetchone()
    if row and row[4] and not refresh:
        return {"event": e, "article": {"url": row[0] or url, "title": row[1], "site": row[2],
                                         "published": row[3], "text": row[4],
                                         "fetched_at": row[6].isoformat() if row[6] else None}, "error": None}
    art, err = reader.fetch(url)
    with db_cursor(commit=True) as cur:
        if art:
            cur.execute("INSERT INTO outside_articles (url, final_url, title, site, published, body, error, attempts, fetched_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, NULL, 1, now()) "
                        "ON CONFLICT (url) DO UPDATE SET final_url = EXCLUDED.final_url, title = EXCLUDED.title, "
                        "site = EXCLUDED.site, published = EXCLUDED.published, body = EXCLUDED.body, error = NULL, "
                        "attempts = outside_articles.attempts + 1, fetched_at = now()",
                        (url, art["url"], art["title"], art["site"], art["published"], art["text"]))
        else:
            cur.execute("INSERT INTO outside_articles (url, error, attempts, fetched_at) VALUES (%s, %s, 1, now()) "
                        "ON CONFLICT (url) DO UPDATE SET error = EXCLUDED.error, attempts = outside_articles.attempts + 1, "
                        "fetched_at = now()", (url, err))
    if not art:
        return {"event": e, "article": None, "error": err, "notes": e.get("notes")}
    return {"event": e, "article": {"url": art["url"], "title": art["title"], "site": art["site"],
                                     "published": art["published"], "text": art["text"],
                                     "fetched_at": datetime.now(timezone.utc).isoformat()}, "error": None}


class BulkRequest(BaseModel):
    ids: Optional[list[int]] = None
    zone_id: Optional[int] = None


@router.post("/dismiss-all")
def dismiss_all(payload: BulkRequest, user: dict = Depends(auth.require_user)):
    with db_cursor(commit=True) as cur:
        if payload.ids:
            cur.execute("UPDATE outside_events SET status = 'dismissed' "
                        "WHERE id = ANY(%s) AND status IN ('new', 'read')", (payload.ids,))
        elif payload.zone_id is not None:
            cur.execute("UPDATE outside_events SET status = 'dismissed' "
                        "WHERE %s = ANY(zone_ids) AND status IN ('new', 'read')", (payload.zone_id,))
        else:
            cur.execute("UPDATE outside_events SET status = 'dismissed' WHERE status IN ('new', 'read')")
        count = cur.rowcount
    audit.record("outside_event.dismiss", user=user, object_type="outside_events", object_id=None,
                 object_label="Outside events", detail={"count": count, "zone_id": payload.zone_id})
    return {"dismissed": count}


class SendRequest(BaseModel):
    fetch_article: bool = True
    source_note: Optional[str] = Field(default=None, max_length=300)


def _document_body(e: dict, article, fetch_error) -> str:
    credit = CREDIT[e["source"]]
    head = [e["title"], "",
            f"Outside event — {credit['name']} ({credit['url']}). Machine-gathered open-source "
            f"data: not verified by this team.",
            f"Source record: {e['source'].upper()} {e['source_id']}"]
    if e.get("occurred_on"):
        head.append(f"Date: {e['occurred_on']}")
    if e.get("place"):
        head.append(f"Place: {e['place']} ({e['lat']:.5f}, {e['lon']:.5f})"
                    + (f" — placed at {e['precision']} level" if e.get("precision") else ""))
    if e.get("category") or e.get("code"):
        head.append(f"Type: {e.get('category') or ''}" + (f" ({e['code']})" if e.get("code") else ""))
    if e.get("actor1") or e.get("actor2"):
        head.append(f"Actors: {e.get('actor1') or '—'} → {e.get('actor2') or '—'}")
    if e.get("fatalities") is not None:
        head.append(f"Fatalities reported: {e['fatalities']}")
    if e.get("num_sources") is not None:
        head.append(f"Reported by {e['num_sources']} source(s), {e.get('num_articles') or 0} article(s)")
    if e.get("sources_named"):
        head.append(f"Sources: {e['sources_named']}")
    if e.get("url"):
        head.append(f"Article: {e['url']}")
    if fetch_error:
        head.append(f"The article's text was not retrieved: {fetch_error}")
    body = article or e.get("notes") or "(No article text; the record's details are above.)"
    return "\n".join(head) + "\n\n" + ("-" * 60) + "\n\n" + body


@router.post("/{event_id}/to-document", status_code=201)
def send_to_documents(event_id: int, payload: SendRequest, user: dict = Depends(auth.require_user)):
    """The only way an outside event reaches the case file: as a document, by
    a person, with where it came from written at the top."""
    with db_cursor() as cur:
        e = _get(cur, event_id)
    if e["status"] == "sent" and e["attachment_id"]:
        raise HTTPException(status_code=409, detail={"message": "That event is already in Documents.",
                                                     "document_id": e["attachment_id"]})
    article, fetch_error = (None, None)
    if payload.fetch_article and e.get("url"):
        with db_cursor() as cur:
            cur.execute("SELECT title, body FROM outside_articles WHERE url = %s AND body IS NOT NULL", (e["url"],))
            kept = cur.fetchone()
        if kept:
            article = ((kept[0] + "\n\n") if kept[0] else "") + kept[1]
        else:
            article, fetch_error = fetch_article(e["url"])
    text = _document_body(e, article, fetch_error)
    content = text.encode("utf-8")

    now = datetime.now(timezone.utc)
    rel_dir = os.path.join(str(now.year), f"{now.month:02d}")
    os.makedirs(os.path.join(UPLOAD_DIR, rel_dir), exist_ok=True)
    storage_path = os.path.join(rel_dir, f"{uuid.uuid4().hex}.txt")
    abs_path = os.path.join(UPLOAD_DIR, storage_path)
    with open(abs_path, "wb") as fh:
        fh.write(content)
    title = (e["title"] or "Outside event")[:300]
    safe = "".join(c if c.isalnum() or c in " -_" else "-" for c in title).strip()
    filename = ("-".join(safe.split())[:80] or "outside-event") + ".txt"
    note = (payload.source_note or "").strip() or f"Outside event: {CREDIT[e['source']]['name']}"
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO attachments (filename, title, source_note, is_pasted, "
                "        storage_path, mime_type, file_size_bytes, uploaded_by) "
                "VALUES (%s, %s, %s, TRUE, %s, 'text/plain', %s, %s) RETURNING id",
                (filename, title, note, storage_path, len(content), user["id"]))
            document_id = cur.fetchone()[0]
            cur.execute("UPDATE outside_events SET status = 'sent', attachment_id = %s, "
                        "sent_by = %s, sent_at = now() WHERE id = %s", (document_id, user["id"], event_id))
            cur.execute("UPDATE outside_events SET status = 'read' WHERE dup_of = %s AND status = 'new'",
                        (event_id,))
    except Exception:
        try:
            os.remove(abs_path)
        except OSError:
            pass
        raise
    audit.record("outside_event.to_document", user=user, object_type="attachment",
                 object_id=document_id, object_label=title,
                 detail={"source": e["source"], "source_id": e["source_id"], "event_id": event_id,
                         "fetched_article": bool(article), "fetch_error": fetch_error})
    return {"document_id": document_id, "title": title, "fetched_article": bool(article),
            "fetch_error": fetch_error}


# ---- settings (admin) ------------------------------------------------------------------------

SETTING_FIELDS = (
    "gdelt_enabled", "gdelt_interval_minutes", "gdelt_request_spacing_seconds", "gdelt_backfill_hours",
    "gdelt_root_codes", "gdelt_min_sources", "gdelt_city_only", "gdelt_last_file", "gdelt_last_poll_at",
    "gdelt_last_error", "acled_enabled", "acled_username", "acled_password", "acled_interval_minutes",
    "acled_request_spacing_seconds", "acled_backfill_days", "acled_last_poll_at", "acled_last_error",
    "retention_days", "pull_requested_at", "updated_at", "prefetch_articles", "article_spacing_seconds",
    "articles_per_pass", "dedupe_rules", "dedupe_model", "dedupe_model_threshold",
    "triage_enabled", "triage_model", "triage_acled", "triage_per_pass", "triage_min_severity",
    "triage_examples", "triage_last_error")


def _settings(cur) -> dict:
    cur.execute(f"SELECT {', '.join(SETTING_FIELDS)} FROM outside_event_settings WHERE id = 1")
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO outside_event_settings (id) VALUES (1) ON CONFLICT DO NOTHING")
        cur.execute(f"SELECT {', '.join(SETTING_FIELDS)} FROM outside_event_settings WHERE id = 1")
        row = cur.fetchone()
    s = dict(zip(SETTING_FIELDS, row))
    # The password never leaves the server: only whether there is one.
    s["acled_password_set"] = bool(s.pop("acled_password"))
    for k in ("gdelt_last_poll_at", "acled_last_poll_at", "pull_requested_at", "updated_at"):
        if s[k] is not None:
            s[k] = s[k].isoformat()
    for k in ("gdelt_request_spacing_seconds", "acled_request_spacing_seconds", "article_spacing_seconds",
              "dedupe_model_threshold"):
        s[k] = float(s[k])
    cur.execute("SELECT count(*) FILTER (WHERE body IS NOT NULL), count(*) FILTER (WHERE error IS NOT NULL) "
                "FROM outside_articles")
    s["articles"] = dict(zip(("read", "failed"), cur.fetchone()))
    cur.execute("SELECT count(*) FROM outside_events WHERE dup_of IS NOT NULL")
    s["folded"] = cur.fetchone()[0]
    try:
        cur.execute("SELECT COALESCE(ollama_embed_model, '') FROM app_settings LIMIT 1")
        r = cur.fetchone()
        s["embed_model"] = (r[0] if r else "") or os.environ.get("OLLAMA_EMBED_MODEL", "")
    except Exception:
        s["embed_model"] = os.environ.get("OLLAMA_EMBED_MODEL", "")
    try:
        cur.execute("SELECT COALESCE(ollama_model, '') FROM app_settings LIMIT 1")
        r = cur.fetchone()
        s["assistant_model"] = (r[0] if r else "") or os.environ.get("OLLAMA_MODEL", "")
    except Exception:
        s["assistant_model"] = os.environ.get("OLLAMA_MODEL", "")
    s["triage_model"] = s["triage_model"] or ""
    cur.execute("SELECT count(*) FILTER (WHERE triaged_at IS NOT NULL AND triage_by = 'model'), "
                f"       count(*) FILTER (WHERE {FILTERED_SQL.replace('e.', '')}), "
                "       count(*) FILTER (WHERE triaged_at IS NULL AND status IN ('new', 'read') "
                "                          AND (source = 'gdelt' OR %s)), "
                "       count(*) FILTER (WHERE triage_by = 'analyst') "
                "FROM outside_events WHERE dup_of IS NULL", (s["triage_min_severity"], s["triage_acled"]))
    s["triage_counts"] = dict(zip(("checked", "filtered", "waiting", "corrected"), cur.fetchone()))
    cur.execute("SELECT count(*) FROM outside_triage_corrections")
    s["triage_counts"]["examples"] = cur.fetchone()[0]
    s["triage_categories"] = [{"key": k, "label": v} for k, v in TRIAGE_CATEGORIES.items()]
    s["gdelt_root_codes"] = [c for c in (s["gdelt_root_codes"] or "").split(",") if c]
    cur.execute("SELECT z.id, COALESCE(ze.name, z.name), (z.valid_until IS NOT NULL AND z.valid_until <= now()), "
                "       z.outside_focus "
                "FROM map_zones z LEFT JOIN entities ze ON ze.id = z.entity_id WHERE z.outside_events ORDER BY 2")
    s["zones"] = [{"id": r[0], "name": r[1], "expired": r[2], "focus": r[3] or ""} for r in cur.fetchall()]
    cur.execute("SELECT source, count(*), count(*) FILTER (WHERE status = 'new') FROM outside_events GROUP BY source")
    s["counts"] = {r[0]: {"total": r[1], "unread": r[2]} for r in cur.fetchall()}
    s["limits"] = {k: {"min": v[0], "max": v[1]} for k, v in LIMITS.items()}
    s["root_code_choices"] = [{"code": c, "label": l} for c, l in ROOT_CODES]
    s["credit"] = CREDIT
    return s


@admin_router.get("/settings")
def get_settings(user: dict = Depends(auth.require_admin)):
    with db_cursor(commit=True) as cur:
        return _settings(cur)


class SettingsUpdate(BaseModel):
    gdelt_enabled: Optional[bool] = None
    gdelt_interval_minutes: Optional[int] = None
    gdelt_request_spacing_seconds: Optional[float] = None
    gdelt_backfill_hours: Optional[int] = None
    gdelt_root_codes: Optional[list[str]] = None
    gdelt_min_sources: Optional[int] = None
    gdelt_city_only: Optional[bool] = None
    acled_enabled: Optional[bool] = None
    acled_username: Optional[str] = Field(default=None, max_length=200)
    # Empty string clears it; absent leaves it.
    acled_password: Optional[str] = Field(default=None, max_length=500)
    acled_interval_minutes: Optional[int] = None
    acled_request_spacing_seconds: Optional[float] = None
    acled_backfill_days: Optional[int] = None
    retention_days: Optional[int] = None
    prefetch_articles: Optional[bool] = None
    article_spacing_seconds: Optional[float] = None
    articles_per_pass: Optional[int] = None
    dedupe_rules: Optional[bool] = None
    dedupe_model: Optional[bool] = None
    dedupe_model_threshold: Optional[float] = None
    triage_enabled: Optional[bool] = None
    # Empty: the assistant's model.
    triage_model: Optional[str] = Field(default=None, max_length=200)
    triage_acled: Optional[bool] = None
    triage_per_pass: Optional[int] = None
    triage_min_severity: Optional[int] = None
    triage_examples: Optional[int] = None
    # Set to the fastest the sources allow (each field's minimum).
    fastest: Optional[bool] = None


@admin_router.put("/settings")
def update_settings(payload: SettingsUpdate, user: dict = Depends(auth.require_admin)):
    fields = payload.model_dump(exclude_unset=True)
    fastest = fields.pop("fastest", None)
    if fastest:
        for k in ("gdelt_interval_minutes", "gdelt_request_spacing_seconds",
                  "acled_interval_minutes", "acled_request_spacing_seconds"):
            fields[k] = LIMITS[k][0]
    for k, (lo, hi) in LIMITS.items():
        if k in fields and fields[k] is not None and not (lo <= fields[k] <= hi):
            raise HTTPException(status_code=400, detail=f"{k.replace('_', ' ')}: between {lo} and {hi}"
                                + (" — the source's own terms set the minimum" if k in (
                                    "gdelt_interval_minutes", "gdelt_request_spacing_seconds") else ""))
    if "gdelt_root_codes" in fields and fields["gdelt_root_codes"] is not None:
        codes = sorted({c.strip().zfill(2) for c in fields["gdelt_root_codes"]})
        valid = {c for c, _ in ROOT_CODES}
        if not codes or any(c not in valid for c in codes):
            raise HTTPException(status_code=400, detail="Choose at least one event type (CAMEO 01-20).")
        fields["gdelt_root_codes"] = ",".join(codes)
    if "acled_username" in fields:
        fields["acled_username"] = (fields["acled_username"] or "").strip() or None
    if "triage_model" in fields:
        fields["triage_model"] = (fields["triage_model"] or "").strip() or None
    if "acled_password" in fields:
        fields["acled_password"] = fields["acled_password"] or None
    if "acled_username" in fields or "acled_password" in fields:
        # New credentials: the old token was for the old account.
        fields["acled_token"], fields["acled_token_expires"] = None, None
    fields = {k: v for k, v in fields.items() if v is not None or k in (
        "acled_username", "acled_password", "acled_token", "acled_token_expires", "triage_model")}
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    with db_cursor(commit=True) as cur:
        _settings(cur)
        sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = now()"
        cur.execute(f"UPDATE outside_event_settings SET {sets} WHERE id = 1", list(fields.values()))
        out = _settings(cur)
    shown = {k: ("(set)" if k == "acled_password" and v else v) for k, v in fields.items()
             if k not in ("acled_token", "acled_token_expires")}
    audit.record("outside_events.settings", user=user, object_type="settings", object_id=None,
                 object_label="Outside events", detail=shown)
    return out


@admin_router.post("/pull-now")
def pull_now(user: dict = Depends(auth.require_admin)):
    """Make each enabled source due now. The spacing between requests still
    applies; this only skips waiting for the next interval."""
    with db_cursor(commit=True) as cur:
        _settings(cur)
        cur.execute("UPDATE outside_event_settings SET pull_requested_at = now() WHERE id = 1")
        out = _settings(cur)
    audit.record("outside_events.pull_now", user=user, object_type="settings", object_id=None,
                 object_label="Outside events")
    return out


class FocusRequest(BaseModel):
    focus: Optional[str] = Field(default=None, max_length=500)


@admin_router.put("/zones/{zone_id}/focus")
def set_focus(zone_id: int, payload: FocusRequest, user: dict = Depends(auth.require_admin)):
    """What the team cares about in an area, in its own words; the model's
    triage weighs events against it."""
    focus = (payload.focus or "").strip() or None
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE map_zones SET outside_focus = %s WHERE id = %s AND outside_events RETURNING name",
                    (focus, zone_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such area (a zone marked for outside events).")
        out = _settings(cur)
    audit.record("outside_events.focus", user=user, object_type="map_zones", object_id=zone_id,
                 object_label=row[0], detail={"focus": focus})
    return out


class RetriageRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=365)


@admin_router.post("/retriage")
def retriage(payload: RetriageRequest, user: dict = Depends(auth.require_admin)):
    """Have the model judge again the open incidents of the last `days` (after
    changing the model, an area's focus or the examples). A person's
    corrections stay."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE outside_events SET triaged_at = NULL, triage_attempts = 0, triage_error = NULL "
                    "WHERE dup_of IS NULL AND status IN ('new', 'read') AND triaged_at IS NOT NULL "
                    "AND triage_by IS DISTINCT FROM 'analyst' "
                    "AND COALESCE(occurred_on, created_at::date) >= (now() - make_interval(days => %s))::date",
                    (payload.days,))
        count = cur.rowcount
        out = _settings(cur)
    audit.record("outside_events.retriage", user=user, object_type="settings", object_id=None,
                 object_label="Outside events", detail={"days": payload.days, "count": count})
    return {**out, "requeued": count}


@admin_router.delete("/corrections")
def forget_corrections(user: dict = Depends(auth.require_admin)):
    """Stop showing the model the team's earlier corrections. The corrected
    events keep their corrections."""
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM outside_triage_corrections")
        count = cur.rowcount
        out = _settings(cur)
    audit.record("outside_events.forget_corrections", user=user, object_type="settings", object_id=None,
                 object_label="Outside events", detail={"count": count})
    return out
