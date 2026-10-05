"""Export packages: dossiers, hotspot workings, and the executive summary.

Three exports beyond the per-report package that already existed:

  * **Dossier** — one entity and everything one hop from it. Three shapes
    (org / target / plain) that differ in how the same material is *arranged*,
    not in what is collected. See SHAPES below for why that is one code path
    and not three.
  * **Hotspot** — a Location, its hotspot arithmetic, and every record that
    produced it. Counted by the same SQL as the dashboard panel
    (insights.hotspot_detail), because a package that disagreed with the panel
    that sent you to it would be worse than no package.
  * **Executive summary** — a period's work, by the numbers and by analyst.

WHAT THESE ARE NOT

None of them is an assessment. They collect, arrange and count what is already
in the case file; no export writes a conclusion the analyst did not write, and
nothing here calls a model. An executive summary that said "activity is
escalating" would be inventing a judgement out of a bar chart, so it reports
counts and lets the reader draw it.

ACCESS

Any logged-in user can produce any of these. Every one of them contains only
records that user can already read in the app, so an export boundary would be
theatre — but each one is audited, because the difference between reading a
record on screen and carrying fifty of them out as a file is the whole reason
the audit trail exists.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

import audit
import bolo_pdf
import auth
import contacts
import entities
import insights
import map_pdf
import map_render
import package_pdf
import report_pdf
from db import db_cursor

router = APIRouter(prefix="/api/exports", tags=["exports"])

# The three framings a dossier can take. They select the same records — the
# entity, one hop of relationships, every report that mentions it, its
# attachments — and differ only in how those are grouped and headed.
#
# Kept as one code path because the alternative was two near-identical builders
# that would drift: a fix to how contacts print would land in one and not the
# other, and the difference would show up as a bug report six weeks later.
# What genuinely differs between an "org report" and a "target package" is the
# question the reader is holding, and that is a matter of grouping and wording.
SHAPES = {
    "org": {
        "label": "Organisation report",
        "subtitle": "Structure, membership and holdings",
        # Relationship types that answer "who belongs to this organisation".
        # Everything else still prints, under Other connections.
        "primary_groups": [
            ("People", ("member_of", "employed_by", "affiliated_with", "associate_of")),
            ("Holdings and control", ("controls", "owns", "located_at")),
            ("Standing and conflict", ("in_conflict_with", "financed_by")),
        ],
    },
    "target": {
        "label": "Target package",
        "subtitle": "Everything on file for one record",
        "primary_groups": [
            ("Status and disposition", ()),   # rendered from details, not edges
            ("Affiliations", ("member_of", "employed_by", "affiliated_with", "associate_of")),
            ("Family", ("spouse_of", "significant_of", "parent_of", "child_of", "family_of")),
            ("Places and movements", ("located_at", "present_at")),
            ("Contact and communications", ("communicated_with",)),
        ],
    },
    "plain": {
        "label": "Entity dossier",
        "subtitle": "The record and what it connects to",
        "primary_groups": [],   # one flat, chronological list
    },
}
DEFAULT_SHAPE = "plain"

# How many days an executive summary covers by default, and what it will accept.
EXEC_WINDOW_CHOICES = (7, 14, 30, 60, 90)
DEFAULT_EXEC_WINDOW = 30


def _header_safe_filename(filename: str) -> str:
    """Same treatment as reports._header_safe_filename — an entity name is
    freeform text and goes into a Content-Disposition header."""
    return "".join(c for c in (filename or "") if c.isprintable() and c not in '"\\;\r\n') or "export.pdf"


# ---------------------------------------------------------------------------
# Dossier
# ---------------------------------------------------------------------------

def _neighbour_details(cur, entity_ids: list[str]) -> dict:
    """The facts about a one-hop neighbour that belong in a package.

    An organisation report that lists "Ruth Okafor" and stops has told the
    reader nothing they could act on; the same line with her occupation and
    disposition is the point of the page. This pulls only the columns a
    printed dossier actually shows, for every neighbour at once, rather than
    calling get_entity per neighbour — on a well-connected organisation that
    would be forty round trips and forty times the data.
    """
    if not entity_ids:
        return {}
    cur.execute(
        """
        SELECT e.id, e.entity_type, e.name, e.description, e.is_active,
               p.occupation, p.life_status, p.disposition,
               COALESCE(p.alignment, o.alignment, s.alignment, v.alignment),
               o.org_type, l.environment,
               l.address, l.lat, l.lng,
               ev.event_type, ev.started_at, ev.expires_at,
               v.make, v.model, v.color, v.license_plate, v.style
        FROM entities e
        LEFT JOIN person_details p ON p.entity_id = e.id
        LEFT JOIN organization_details o ON o.entity_id = e.id
        LEFT JOIN location_details l ON l.entity_id = e.id
        LEFT JOIN event_details ev ON ev.entity_id = e.id
        LEFT JOIN vehicle_details v ON v.entity_id = e.id
        LEFT JOIN source_details s ON s.entity_id = e.id
        WHERE e.id = ANY(%s)
        """,
        (entity_ids,),
    )
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {
            "id": r[0], "entity_type": r[1], "name": r[2], "description": r[3],
            "is_active": r[4],
            "occupation": r[5], "life_status": r[6], "disposition": r[7],
            # One column whatever the kind: the neighbour line asks "whose
            # side is this on", and a Person, an Organization, a Source and a
            # Vehicle all answer it from their own table.
            "alignment": r[8], "org_type": r[9], "environment": r[10],
            "address": r[11], "lat": r[12], "lng": r[13],
            "event_type": r[14], "started_at": r[15], "expires_at": r[16],
            # A vehicle's one-line identity. Not the whole record — this is
            # what a neighbour line has room for, and "white Ford panel van,
            # ABC-123" is the part somebody reading a dossier can act on.
            "make": r[17], "model": r[18], "color": r[19],
            "license_plate": r[20], "style": r[21],
        }
    return out


def _reports_for_entity(cur, entity_id: str) -> list[dict]:
    """Every report that mentions this entity, with the fields a package needs.

    get_entity already returns a report list, but without criticality — and
    precedence is exactly what a reader scanning a target package's reporting
    history needs to see first.
    """
    cur.execute(
        """
        SELECT rep.id, rep.title, rep.status, rep.criticality, rep.credibility_rating,
               rep.created_at, rep.updated_at, u.username
        FROM report_entities re
        JOIN reports rep ON rep.id = re.report_id
        LEFT JOIN users u ON u.id = rep.author_id
        WHERE re.entity_id = %s
        ORDER BY rep.created_at DESC
        """,
        (entity_id,),
    )
    return [
        {"id": r[0], "title": r[1], "status": r[2], "criticality": r[3],
         "credibility_rating": r[4], "created_at": r[5], "updated_at": r[6],
         "author": r[7]}
        for r in cur.fetchall()
    ]


def _full_reports(cur, report_ids: list[str]) -> list[dict]:
    """The linked reports in full — body and photographs — oldest first.

    A package handed to someone outside the platform (a police unit, a
    regulator) has to stand on its own: a list of report titles tells them
    reporting exists and gives them none of it. Oldest first so the reporting
    reads as the account it is, in the order it was learned.
    """
    if not report_ids:
        return []
    cur.execute(
        """
        SELECT rep.id, rep.title, rep.body_markdown, rep.status, rep.criticality,
               rep.credibility_rating, rep.created_at, rep.updated_at, u.username
          FROM reports rep LEFT JOIN users u ON u.id = rep.author_id
         WHERE rep.id = ANY(%s)
         ORDER BY rep.created_at, rep.id
        """, (report_ids,))
    out = [{"id": r[0], "title": r[1], "body_markdown": r[2], "status": r[3],
            "criticality": r[4], "credibility_rating": r[5], "created_at": r[6],
            "updated_at": r[7], "author": r[8], "attachments": []}
           for r in cur.fetchall()]
    by_id = {r["id"]: r for r in out}
    cur.execute(
        "SELECT id, report_id, filename, title, mime_type, storage_path, source_note "
        "  FROM attachments WHERE report_id = ANY(%s) AND archived_at IS NULL ORDER BY id",
        (report_ids,))
    for a in cur.fetchall():
        by_id[a[1]]["attachments"].append({
            "id": a[0], "filename": a[3] or a[2], "mime_type": a[4],
            "storage_path": a[5], "source_note": a[6]})
    return out


def _board_entries(cur, entity_id: str) -> list[dict]:
    """Active BOLO / roster entries for this record, for the cover page."""
    cur.execute(
        "SELECT b.board, b.urgency, b.reason, b.role, b.callsign, b.created_at, b.expires_at, "
        "       bo.label, bo.enabled "
        "  FROM board_entries b JOIN boards bo ON bo.kind = b.board "
        " WHERE b.entity_id = %s AND b.status = 'active'", (entity_id,))
    return [{"board": r[0], "urgency": r[1], "reason": r[2], "role": r[3], "callsign": r[4],
             "created_at": r[5], "expires_at": r[6], "label": r[7] or r[0].upper()}
            for r in cur.fetchall() if r[8]]


def _timeline(entity: dict, neighbours: dict, reports: list) -> list[dict]:
    """One chronology across everything the package holds: when each report
    was filed, when each linked event happened, when each link was learned
    and until when it held. The order things happened in is half of what a
    recipient needs and nothing else in the package gives it to them."""
    items = []
    for r in reports:
        items.append({"when": r["created_at"], "kind": "Report",
                      "what": r["title"], "note": r.get("criticality") or ""})
    for rel in entity.get("relationships") or []:
        n = neighbours.get(rel.get("other_entity_id")) or {}
        if n.get("entity_type") == "event" and n.get("started_at"):
            items.append({"when": n["started_at"], "kind": "Event", "what": n["name"],
                          "note": n.get("event_type") or ""})
        if rel.get("discovery_date"):
            wording = (rel.get("reads_as") or rel.get("relationship_type") or "").replace("_", " ")
            note = f"until {rel['expires_on']}" if rel.get("expires_on") else ""
            if rel.get("expired"):
                note = f"expired {rel['expires_on']}"
            items.append({"when": rel["discovery_date"], "kind": "Link learned",
                          "what": f"{wording} {rel.get('other_entity_name')}", "note": note})
    def key(i):
        w = i["when"]
        return w.isoformat() if hasattr(w, "isoformat") else str(w)
    return sorted(items, key=key)


def gather_dossier(entity_id: str, shape: str, user: dict, *,
                   prepared_for: str | None = None, purpose: str | None = None,
                   contacts_scope: str = "all") -> dict:
    """Everything a dossier prints, in one dict.

    One hop: the entity, each directly related entity with the facts worth
    printing about it, every report that mentions the entity, and the entity's
    own attachments. Deliberately not two hops — on the contested-metro sample
    a two-hop package from a large organization runs past sixty pages, and a package
    nobody reads to the end is not a better package.
    """
    entity = entities.get_entity(entity_id, user=user)

    with db_cursor() as cur:
        neighbour_ids = sorted({
            rel["other_entity_id"] for rel in entity["relationships"]
            if rel.get("other_entity_id")
        })
        neighbours = _neighbour_details(cur, neighbour_ids)
        linked_reports = _reports_for_entity(cur, entity_id)
        full_reports = _full_reports(cur, [r["id"] for r in linked_reports])
        boards_on = _board_entries(cur, entity_id)
        _attach_storage_paths(cur, entity["attachments"])
        package_map = _package_map(cur, entity, neighbours)
        # Contacts for the neighbours too: in an organisation report, "how do I
        # reach this person" is most of the value, and it lives one table over.
        neighbour_contacts = {}
        for nid, n in neighbours.items():
            if n["entity_type"] in contacts.CONTACTABLE_TYPES:
                # One line per neighbour, so only the first preferred contact —
                # a neighbour's full contact list belongs in that neighbour's
                # own dossier, not inlined into somebody else's.
                preferred = contacts.preferred_for_entity(cur, nid)
                if preferred:
                    neighbour_contacts[nid] = preferred[0]

    return {
        "entity": entity,
        "shape": shape,
        "shape_spec": SHAPES[shape],
        "neighbours": neighbours,
        "neighbour_contacts": neighbour_contacts,
        "reports": linked_reports,
        "full_reports": full_reports,
        "boards": boards_on,
        "timeline": _timeline(entity, neighbours, linked_reports),
        "prepared_for": (prepared_for or "").strip() or None,
        "purpose": (purpose or "").strip() or None,
        "contacts_scope": contacts_scope,
        "map": package_map,
    }


# The kinds a package's map can draw.
_MAPPABLE = ("location", "zone", "route")


def _package_map(cur, entity: dict, neighbours: dict):
    """(image, meta) for the package's map page, or None when nothing in it
    has a place.

    The record itself if it is a place, a zone or a route, and every directly
    linked one that is -- the same one-hop rule as the rest of the package. A
    person's package shows the places, zones and routes they are linked to,
    which is usually the most useful page in it for whoever reads it next.
    Only those records are drawn, not everything else that happens to be in
    the same rectangle of the case file.
    """
    ids = [nid for nid, n in neighbours.items() if n.get("entity_type") in _MAPPABLE]
    if entity["entity_type"] in _MAPPABLE:
        ids.append(entity["id"])
    bbox = map_render.bounds_of_entities(cur, ids)
    if bbox is None:
        return None
    width, height = 1200, 840
    try:
        return map_render.render(cur, map_render.pad_bbox(bbox), width, height,
                                 entity_ids=set(ids), highlight={entity["id"]})
    except Exception:
        # A map that cannot be drawn must not cost anyone the package.
        return None


@router.get("/map.pdf")
def export_map_pdf(
    north: float = Query(..., ge=-90, le=90), south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180), west: float = Query(..., ge=-180, le=180),
    source_id: Optional[int] = Query(default=None),
    title: str = Query(default="Map", max_length=200),
    note: Optional[str] = Query(default=None, max_length=300),
    paper: str = Query(default="letter"),
    orientation: str = Query(default="landscape"),
    zones: bool = Query(default=True), routes: bool = Query(default=True),
    locations: bool = Query(default=True), labels: bool = Query(default=True),
    include_expired: bool = Query(default=True),
    user: dict = Depends(auth.require_user),
):
    """The Map page's current view, as a one-page PDF to print or attach."""
    if north <= south or east <= west:
        raise HTTPException(status_code=400, detail="That view has no area.")
    if paper not in map_pdf.PAPERS or orientation not in ("landscape", "portrait"):
        raise HTTPException(status_code=400, detail="paper is letter or a4; orientation landscape or portrait")
    width, height = map_pdf.image_px_for(paper, orientation)
    with db_cursor() as cur:
        img, meta = map_render.render(
            cur, (south, west, north, east), width, height, source_id=source_id,
            zones=zones, routes=routes, locations=locations, labels=labels,
            include_expired=include_expired, fit_exact=True)
    pdf_bytes = map_pdf.build_map_pdf(img, meta, title=title.strip() or "Map",
                                      note=(note or "").strip() or None, paper=paper,
                                      orientation=orientation, generated_by=user["username"])
    audit.record("export.map", user=user, object_type="map", object_label=title,
                 detail={"bbox": [south, west, north, east], "zoom": meta["zoom"],
                         "counts": meta["counts"], "tiles_missing": meta["tiles_missing"],
                         "note": note})
    filename = _header_safe_filename(f"map-{title.strip() or 'view'}-{datetime.now(timezone.utc):%Y%m%d}.pdf")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _attach_storage_paths(cur, attachments: list) -> None:
    """As reports._attach_storage_paths. Duplicated rather than imported to
    keep exports.py from depending on the reports router module, which imports
    this one's sibling — the import cycle is the only reason."""
    ids = [a["id"] for a in attachments or []]
    if not ids:
        return
    cur.execute("SELECT id, storage_path FROM attachments WHERE id = ANY(%s)", (ids,))
    paths = dict(cur.fetchall())
    for att in attachments:
        att["storage_path"] = paths.get(att["id"])


@router.get("/entities/{entity_id}/dossier.pdf")
def export_dossier(
    entity_id: str,
    shape: str = Query(default=DEFAULT_SHAPE, description=f"One of {tuple(SHAPES)}"),
    # Printed on the cover. A package handed outside the team — to a police
    # unit, to a regulator — should say who it was made for and why, so a
    # copy found later on a desk explains itself.
    prepared_for: Optional[str] = Query(default=None, max_length=200),
    purpose: Optional[str] = Query(default=None, max_length=500),
    # Every contact point, or only the ones marked preferred. "all" by
    # default now that a package is meant to stand on its own; "preferred"
    # keeps the old, narrower behaviour for a wider audience.
    contacts_scope: str = Query(default="all", alias="contacts"),
    user: dict = Depends(auth.require_user),
):
    if shape not in SHAPES:
        raise HTTPException(
            status_code=400,
            detail=f'shape must be one of {tuple(SHAPES)}',
        )
    if contacts_scope not in ("all", "preferred"):
        raise HTTPException(status_code=400, detail="contacts must be 'all' or 'preferred'")
    data = gather_dossier(entity_id, shape, user, prepared_for=prepared_for,
                          purpose=purpose, contacts_scope=contacts_scope)
    pdf_bytes = package_pdf.build_dossier(data, user["username"])
    filename = package_pdf.dossier_filename(data["entity"], shape)

    audit.record(
        "export.dossier", user=user, object_type="entity", object_id=entity_id,
        object_label=data["entity"]["name"],
        detail={
            "shape": shape,
            # Who it was made for is the first question about any copy that
            # left the building.
            "prepared_for": data["prepared_for"],
            "purpose": data["purpose"],
            "contacts": contacts_scope,
            # Naming what left is the point of the entry: a dossier carries
            # every neighbour's details out with it, not just the subject's.
            "neighbours_included": sorted(data["neighbours"]),
            "reports_included": [r["id"] for r in data["reports"]],
            "size_bytes": len(pdf_bytes),
        },
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_header_safe_filename(filename)}"'},
    )


# ---------------------------------------------------------------------------
# Hotspot
# ---------------------------------------------------------------------------

def gather_hotspot(location_id: str, days: int, user: dict) -> dict:
    """The location, its hotspot arithmetic, and every contributing record.

    The records come back from the same SQL the dashboard panel uses, so the
    package and the panel can never disagree about what made a place hot.
    """
    location = entities.get_entity(location_id, user=user)
    if location["entity_type"] != "location":
        raise HTTPException(
            status_code=400,
            detail="Hotspot packages are for Locations. Use the dossier export for other entities.",
        )

    with db_cursor() as cur:
        working = insights.hotspot_detail(cur, location_id, days)
        _attach_storage_paths(cur, location["attachments"])

        record_ids = [r["id"] for r in (working or {}).get("records", [])]
        report_ids = [r["id"] for r in (working or {}).get("records", []) if r["kind"] == "report"]
        event_ids = [r["id"] for r in (working or {}).get("records", []) if r["kind"] == "event"]

        reports = []
        if report_ids:
            cur.execute(
                """
                SELECT rep.id, rep.title, rep.status, rep.criticality,
                       rep.credibility_rating, rep.created_at, u.username
                FROM reports rep LEFT JOIN users u ON u.id = rep.author_id
                WHERE rep.id = ANY(%s)
                ORDER BY rep.created_at DESC
                """,
                (report_ids,),
            )
            reports = [
                {"id": r[0], "title": r[1], "status": r[2], "criticality": r[3],
                 "credibility_rating": r[4], "created_at": r[5], "author": r[6]}
                for r in cur.fetchall()
            ]

        events = []
        if event_ids:
            cur.execute(
                """
                SELECT e.id, e.name, e.description, d.event_type, d.started_at,
                       d.ended_at, d.expires_at
                FROM entities e LEFT JOIN event_details d ON d.entity_id = e.id
                WHERE e.id = ANY(%s)
                ORDER BY COALESCE(d.started_at, e.created_at) DESC
                """,
                (event_ids,),
            )
            events = [
                {"id": r[0], "name": r[1], "description": r[2], "event_type": r[3],
                 "started_at": r[4], "ended_at": r[5], "expires_at": r[6]}
                for r in cur.fetchall()
            ]

        # Who else is at this place. A hotspot package that lists the traffic
        # but not the people and organisations tied to the location leaves the
        # reader to go and look them up, which is the thing a package is for.
        neighbour_ids = sorted({
            rel["other_entity_id"] for rel in location["relationships"]
            if rel.get("other_entity_id")
        })
        neighbours = _neighbour_details(cur, neighbour_ids)

    return {
        "location": location,
        "working": working,
        "window_days": days,
        "threshold": insights.HOTSPOT_MIN_RECORDS,
        "reports": reports,
        "events": events,
        "neighbours": neighbours,
        "record_count": len(record_ids),
    }


@router.get("/hotspots/{location_id}/package.pdf")
def export_hotspot(
    location_id: str,
    days: int = Query(default=insights.DEFAULT_WINDOW,
                      description=f"Window in days; one of {insights.WINDOW_CHOICES}"),
    user: dict = Depends(auth.require_user),
):
    if days not in insights.WINDOW_CHOICES:
        raise HTTPException(status_code=400,
                            detail=f"days must be one of {insights.WINDOW_CHOICES}")
    data = gather_hotspot(location_id, days, user)
    pdf_bytes = package_pdf.build_hotspot_package(data, user["username"])
    filename = package_pdf.hotspot_filename(data["location"])

    audit.record(
        "export.hotspot", user=user, object_type="entity", object_id=location_id,
        object_label=data["location"]["name"],
        detail={
            "window_days": days,
            "records_included": data["record_count"],
            "reports_included": [r["id"] for r in data["reports"]],
            "events_included": [e["id"] for e in data["events"]],
            "size_bytes": len(pdf_bytes),
        },
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_header_safe_filename(filename)}"'},
    )


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

def _period_counts(cur, days: int) -> dict:
    """Headline counts for the period, each with the previous period beside it.

    A bare "41 reports" tells a team lead nothing — 41 against 12 last month is
    a different conversation from 41 against 58. Every headline figure carries
    its own comparison for that reason, and none of them carries an adjective.
    """
    cur.execute(
        """
        SELECT
          (SELECT count(*) FROM reports WHERE created_at >= now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM reports
             WHERE created_at >= now() - 2 * %(d)s * interval '1 day'
               AND created_at <  now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM entities WHERE created_at >= now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM entities
             WHERE created_at >= now() - 2 * %(d)s * interval '1 day'
               AND created_at <  now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM relationships WHERE created_at >= now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM attachments WHERE uploaded_at >= now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM reports
             WHERE status = 'draft' AND created_at >= now() - %(d)s * interval '1 day'),
          (SELECT count(*) FROM reports
             WHERE criticality IN ('Flash','Immediate')
               AND created_at >= now() - %(d)s * interval '1 day')
        """,
        {"d": days},
    )
    r = cur.fetchone()
    return {
        "reports": r[0], "reports_previous": r[1],
        "entities": r[2], "entities_previous": r[3],
        "relationships": r[4], "attachments": r[5],
        "drafts": r[6], "urgent": r[7],
    }


def _entities_by_type(cur, days: int) -> list[dict]:
    cur.execute(
        """
        SELECT entity_type, count(*)
        FROM entities
        WHERE created_at >= now() - %s * interval '1 day'
        GROUP BY entity_type ORDER BY count(*) DESC, entity_type
        """,
        (days,),
    )
    return [{"entity_type": r[0], "count": r[1]} for r in cur.fetchall()]


def _reports_by_criticality(cur, days: int) -> list[dict]:
    cur.execute(
        """
        SELECT criticality, count(*)
        FROM reports
        WHERE created_at >= now() - %s * interval '1 day'
        GROUP BY criticality
        ORDER BY CASE criticality WHEN 'Flash' THEN 0 WHEN 'Immediate' THEN 1
                                  WHEN 'Priority' THEN 2 WHEN 'Routine' THEN 3
                                  ELSE 4 END
        """,
        (days,),
    )
    return [{"criticality": r[0], "count": r[1]} for r in cur.fetchall()]


def _weekly_by_analyst(cur, days: int) -> dict:
    """Reports filed and entities created, per analyst, per week.

    Weeks rather than days because a daily series over thirty days is thirty
    columns of mostly one and zero, which reads as noise rather than as work.
    generate_series supplies the empty weeks, so a quiet fortnight shows as a
    gap in the chart instead of silently closing up.
    """
    cur.execute(
        """
        WITH weeks AS (
            SELECT generate_series(
                date_trunc('week', now() - %(d)s * interval '1 day'),
                date_trunc('week', now()),
                interval '1 week'
            ) AS week_start
        ),
        people AS (
            SELECT DISTINCT u.id, u.username
            FROM users u
            WHERE EXISTS (SELECT 1 FROM reports r
                          WHERE r.author_id = u.id
                            AND r.created_at >= now() - %(d)s * interval '1 day')
               OR EXISTS (SELECT 1 FROM entities e
                          WHERE e.created_by = u.id
                            AND e.created_at >= now() - %(d)s * interval '1 day')
        )
        SELECT w.week_start, p.username,
               (SELECT count(*) FROM reports r
                 WHERE r.author_id = p.id
                   AND date_trunc('week', r.created_at) = w.week_start),
               (SELECT count(*) FROM entities e
                 WHERE e.created_by = p.id
                   AND date_trunc('week', e.created_at) = w.week_start)
        FROM weeks w CROSS JOIN people p
        ORDER BY w.week_start, p.username
        """,
        {"d": days},
    )
    rows = cur.fetchall()
    weeks, analysts = [], {}
    for week_start, username, report_count, entity_count in rows:
        iso = week_start.date().isoformat()
        if iso not in weeks:
            weeks.append(iso)
        a = analysts.setdefault(username, {"reports": {}, "entities": {}})
        a["reports"][iso] = report_count
        a["entities"][iso] = entity_count

    # Unattributed work is counted separately rather than dropped. Records
    # imported in bulk or created by a since-deleted account have no author,
    # and a chart that silently omitted them would understate the period.
    cur.execute(
        """
        SELECT date_trunc('week', created_at)::date, count(*)
        FROM reports
        WHERE author_id IS NULL AND created_at >= now() - %s * interval '1 day'
        GROUP BY 1
        """,
        (days,),
    )
    unattributed_reports = {r[0].isoformat(): r[1] for r in cur.fetchall()}
    cur.execute(
        """
        SELECT date_trunc('week', created_at)::date, count(*)
        FROM entities
        WHERE created_by IS NULL AND created_at >= now() - %s * interval '1 day'
        GROUP BY 1
        """,
        (days,),
    )
    unattributed_entities = {r[0].isoformat(): r[1] for r in cur.fetchall()}
    if unattributed_reports or unattributed_entities:
        analysts["(unattributed)"] = {
            "reports": unattributed_reports,
            "entities": unattributed_entities,
        }

    return {
        "weeks": weeks,
        "analysts": [
            {
                "username": name,
                "reports": [series["reports"].get(w, 0) for w in weeks],
                "entities": [series["entities"].get(w, 0) for w in weeks],
                "report_total": sum(series["reports"].values()),
                "entity_total": sum(series["entities"].values()),
            }
            for name, series in sorted(analysts.items())
        ],
    }


def gather_executive(days: int, user: dict) -> dict:
    with db_cursor() as cur:
        counts = _period_counts(cur, days)
        by_type = _entities_by_type(cur, days)
        by_criticality = _reports_by_criticality(cur, days)
        weekly = _weekly_by_analyst(cur, days)
        # The window a hotspot can be measured over is a fixed set; an
        # executive period of 60 days has no hotspot window of its own, so the
        # nearest supported one is used and the summary says which.
        hotspot_days = min(insights.WINDOW_CHOICES,
                           key=lambda choice: (abs(choice - days), choice))
        hotspots = insights._hotspots(cur, hotspot_days)
        attention = insights._needs_attention(cur)
    return {
        "window_days": days,
        "generated_at": datetime.now(timezone.utc),
        "counts": counts,
        "entities_by_type": by_type,
        "reports_by_criticality": by_criticality,
        "weekly": weekly,
        "hotspots": hotspots,
        "hotspot_window_days": hotspot_days,
        "needs_attention": attention,
    }


@router.get("/executive-summary.pdf")
def export_executive(
    days: int = Query(default=DEFAULT_EXEC_WINDOW,
                      description=f"Period in days; one of {EXEC_WINDOW_CHOICES}"),
    user: dict = Depends(auth.require_user),
):
    if days not in EXEC_WINDOW_CHOICES:
        raise HTTPException(status_code=400,
                            detail=f"days must be one of {EXEC_WINDOW_CHOICES}")
    data = gather_executive(days, user)
    pdf_bytes = package_pdf.build_executive_summary(data, user["username"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"humint-executive-summary-{days}d-{stamp}.pdf"

    audit.record(
        "export.executive", user=user, object_type="summary", object_id=None,
        object_label=f"Executive summary, {days} days",
        detail={
            "window_days": days,
            # Named because a summary attributes work to individuals: who
            # appeared in it is the part someone might later ask about.
            "analysts_named": [a["username"] for a in data["weekly"]["analysts"]],
            "size_bytes": len(pdf_bytes),
        },
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# BOLO sheet — the lookout board, printed for a wall
# ---------------------------------------------------------------------------

@router.get("/bolo.pdf")
def export_bolo(
    layout: str = Query(default="grid", description="grid (six to a page) or single (one to a page)"),
    # Printed on every page: what someone should do if they see one of these.
    note: Optional[str] = Query(default=None, max_length=300),
    user: dict = Depends(auth.require_user),
):
    if layout not in ("grid", "single"):
        raise HTTPException(status_code=400, detail="layout must be 'grid' or 'single'")
    with db_cursor() as cur:
        cur.execute("SELECT enabled, label FROM boards WHERE kind = 'bolo'")
        row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="The BOLO board is not switched on.")
        label = row[1] or "BOLO"
        # Most urgent first — a wall sheet is read top-left first — then the
        # order the team arranged the board in.
        cur.execute(
            "SELECT b.entity_id, b.urgency, b.reason, b.created_at, b.expires_at, a.storage_path "
            "  FROM board_entries b JOIN entities e ON e.id = b.entity_id "
            "  LEFT JOIN attachments a ON a.id = e.portrait_attachment_id "
            " WHERE b.board = 'bolo' AND b.status = 'active' "
            "   AND (b.expires_at IS NULL OR b.expires_at >= CURRENT_DATE) "
            " ORDER BY CASE b.urgency WHEN 'Critical' THEN 0 WHEN 'Urgent' THEN 1 "
            "          WHEN 'Caution' THEN 2 WHEN 'Info' THEN 3 ELSE 4 END, "
            "          b.sort_order, b.created_at DESC")
        rows = cur.fetchall()
    entries = []
    for entity_id, urgency, reason, created_at, expires_at, portrait_path in rows:
        entity = entities.get_entity(entity_id, user=user)
        vehicle_ids = [r["other_entity_id"] for r in entity.get("relationships") or []
                       if r.get("other_entity_type") == "vehicle"]
        with db_cursor() as cur:
            vehicles = _neighbour_details(cur, vehicle_ids)
        entries.append({"entity": entity, "urgency": urgency, "reason": reason,
                        "created_at": created_at, "expires_at": expires_at,
                        "portrait_path": portrait_path, "vehicles": vehicles})

    pdf_bytes = bolo_pdf.build_bolo_sheet(label, entries, layout, (note or "").strip() or None,
                                          user["username"])
    audit.record("export.bolo", user=user, object_type="board", object_id="bolo",
                 object_label=label,
                 detail={"layout": layout, "entities_included": [e["entity"]["id"] for e in entries],
                         "size_bytes": len(pdf_bytes)})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="humint-bolo-{layout}-{stamp}.pdf"'})
