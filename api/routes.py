"""Routes: a way through, recorded for a reason.

A Route is an entity (type 'route') whose detail is a line: the safe way
across a contested city, the track in to a site in the woods, the path a
vehicle was followed along. Three ways in, one shape out:

  * **drawn** on the Map page -- somebody's plan;
  * **imported** from a KML, KMZ or GPX file (api/map_files.py);
  * **walked** with the field app's route recorder and accepted from the
    field queue (api/field.py), with real times on every point.

Being a record is the point. A route links to the people who use it, the zone
it crosses and the reports that describe it, it turns up in search and on the
network, and a package exported for someone outside carries it on its map.

The record's description is the "why" -- why this route was recorded, which is
the question everyone who opens it later will ask first.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit
import auth
import entities as entities_module
import geometry as geo
from db import db_cursor
from idgen import generate_id

router = APIRouter(prefix="/api", tags=["routes"])

ENVIRONMENT_VALUES = entities_module.ENVIRONMENT_VALUES
TRAVEL_MODES = entities_module.TRAVEL_MODES
ORIGINS = ("drawn", "imported", "field")

# What the map is sent. Enough to draw a city route faithfully at street zoom;
# the stored line is never thinned.
DISPLAY_TOLERANCE_DEG = 0.00001          # about a metre


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    # Why it was recorded. Stored as the record's description.
    description: Optional[str] = Field(default=None, max_length=8000)
    # Leaflet order, [[lat, lon], ...], as the map draws it.
    points: list = Field(min_length=2)
    environment: Optional[str] = None
    travel_mode: Optional[str] = None


class RouteRedraw(BaseModel):
    points: list = Field(min_length=2)


def _check_choices(environment, travel_mode) -> None:
    if environment and environment not in ENVIRONMENT_VALUES:
        raise HTTPException(status_code=400,
                            detail="environment must be one of: " + ", ".join(ENVIRONMENT_VALUES))
    if travel_mode and travel_mode not in TRAVEL_MODES:
        raise HTTPException(status_code=400,
                            detail="travel_mode must be one of: " + ", ".join(TRAVEL_MODES))


def _line_or_400(geometry: dict) -> dict:
    try:
        return geo.normalise_line(geometry)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def insert_route(cur, user: dict, *, name: str, description=None, geometry: dict,
                 origin: str = "drawn", environment=None, travel_mode=None,
                 source_file=None, point_times=None, recorded_from=None,
                 recorded_until=None) -> str:
    """A Route record and its line, in the caller's transaction. Returns the id.

    `point_times`, when given, is epoch milliseconds per point in the order of
    the flattened coordinates; it is dropped if it does not line up, because a
    time attached to the wrong point is worse than none.
    """
    _check_choices(environment, travel_mode)
    line = _line_or_400(geometry)
    count = geo.point_count(line)
    if point_times is not None and len(point_times) != count:
        point_times = None
    bounds = geo.bounds_of(geo.all_positions(line))
    entity_id = generate_id("route", name)
    cur.execute(
        "INSERT INTO entities (id, entity_type, name, description, created_by) "
        "VALUES (%s, 'route', %s, %s, %s)",
        (entity_id, name.strip(), (description or "").strip() or None, user["id"]))
    cur.execute(
        """
        INSERT INTO route_details (entity_id, geometry, min_lat, min_lon, max_lat, max_lon,
                                   length_m, point_count, environment, travel_mode, origin,
                                   source_file, recorded_from, recorded_until, point_times)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (entity_id, json.dumps(line), *bounds, round(geo.line_length_m(line), 1), count,
         environment or None, travel_mode or None, origin, source_file,
         recorded_from, recorded_until,
         json.dumps(point_times) if point_times is not None else None))
    return entity_id


def fetch_route(cur, entity_id: str, with_times: bool = False) -> dict:
    cols = ["geometry", "min_lat", "min_lon", "max_lat", "max_lon", "length_m",
            "point_count", "environment", "travel_mode", "origin", "source_file",
            "recorded_from", "recorded_until"] + (["point_times"] if with_times else [])
    cur.execute(
        f"SELECT e.id, e.name, e.description, e.is_active, {', '.join('r.' + c for c in cols)} "
        "FROM entities e JOIN route_details r ON r.entity_id = e.id WHERE e.id = %s",
        (entity_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Route not found")
    out = {"id": row[0], "name": row[1], "description": row[2], "is_active": row[3]}
    out.update(dict(zip(cols, row[4:])))
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/map/routes")
def list_routes(user: dict = Depends(auth.require_user)):
    """Every live route, thinned for drawing. Archived ones stay off the map."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.name, e.description, r.geometry, r.length_m, r.point_count,
                   r.environment, r.travel_mode, r.origin, r.recorded_from,
                   r.min_lat, r.min_lon, r.max_lat, r.max_lon
            FROM entities e JOIN route_details r ON r.entity_id = e.id
            WHERE e.is_active AND e.merged_into IS NULL
            ORDER BY e.created_at DESC
            """)
        rows = cur.fetchall()
    items = []
    for r in rows:
        line = r[3] if isinstance(r[3], dict) else json.loads(r[3])
        items.append({
            "id": r[0], "name": r[1], "description": r[2],
            "geometry": geo.simplified_line(line, DISPLAY_TOLERANCE_DEG),
            "length_m": r[4], "point_count": r[5], "environment": r[6],
            "travel_mode": r[7], "origin": r[8], "recorded_from": r[9],
            "bounds": [r[10], r[11], r[12], r[13]],
        })
    return {"items": items, "travel_modes": list(TRAVEL_MODES)}


@router.post("/routes", status_code=201)
def create_route(payload: RouteCreate, user: dict = Depends(auth.require_user)):
    """A route drawn on the map."""
    try:
        line = geo.latlon_to_line(payload.points)
    except (ValueError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"Bad point: {exc}")
    with db_cursor(commit=True) as cur:
        entity_id = insert_route(cur, user, name=payload.name, description=payload.description,
                                 geometry=line, origin="drawn",
                                 environment=payload.environment,
                                 travel_mode=payload.travel_mode)
        route = fetch_route(cur, entity_id)
    audit.record("route.create", user=user, object_type="entity", object_id=entity_id,
                 object_label=route["name"],
                 detail={"origin": "drawn", "points": route["point_count"],
                         "length_m": route["length_m"]})
    return route


@router.get("/routes/{entity_id}")
def get_route(entity_id: str, user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        route = fetch_route(cur, entity_id, with_times=True)
    route["has_times"] = bool(route.pop("point_times", None))
    return route


@router.put("/routes/{entity_id}/geometry")
def redraw_route(entity_id: str, payload: RouteRedraw, user: dict = Depends(auth.require_user)):
    """Replace the line with a newly drawn one. Times go: they belonged to the
    points that were walked, and these are not those points."""
    try:
        line = _line_or_400(geo.latlon_to_line(payload.points))
    except (ValueError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"Bad point: {exc}")
    bounds = geo.bounds_of(geo.all_positions(line))
    with db_cursor(commit=True) as cur:
        current = fetch_route(cur, entity_id)
        cur.execute(
            """
            UPDATE route_details SET geometry = %s, min_lat = %s, min_lon = %s,
                   max_lat = %s, max_lon = %s, length_m = %s, point_count = %s,
                   point_times = NULL
            WHERE entity_id = %s
            """,
            (json.dumps(line), *bounds, round(geo.line_length_m(line), 1),
             geo.point_count(line), entity_id))
        cur.execute("UPDATE entities SET updated_at = now(), retention_due_at = NULL "
                    "WHERE id = %s", (entity_id,))
        route = fetch_route(cur, entity_id)
    audit.record("route.redraw", user=user, object_type="entity", object_id=entity_id,
                 object_label=route["name"],
                 detail={"points_before": current["point_count"],
                         "points_after": route["point_count"]})
    return route
