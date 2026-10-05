"""KML, KMZ and GPX in and out.

The formats everything else speaks. ATAK, Google Earth, CalTopo, Gaia, a
handheld GPS and most phone mapping apps all read and write at least one of
them, so this is how a route reaches this app from outside and how it leaves
again to somebody who will never log in.

IN -- POST /api/map/import, in two steps:

  1. `mode=preview` parses the file and lists what is in it: each line, area
     and point with its name, size and what it would become.
  2. `mode=commit` parses it again with the analyst's choices (which to keep,
     what to call them, how to assess the areas) and makes the records.
     Lines become Routes, areas become Zones, points become Locations.

The file is sent twice rather than parked on the server between the steps: a
half-finished import leaves nothing behind, and there is no temp store to
clean. The original is kept as an attachment on every record made from it,
so "where did this come from" is always answerable.

OUT -- one record (`/api/routes/{id}/export`, `/api/map/zones/{id}/export`) or
everything live on the map (`/api/map/export`), as KML, KMZ or (routes only)
GPX. Times recorded by the field app go out with the points.

Untrusted input, so: size caps before parsing, a cap on what a KMZ may
decompress to, and the standard library's XML parser, which does not fetch
external entities.
"""

import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

import audit
import auth
import entities as entities_module
import geometry as geo
import routes as routes_module
import zones as zones_module
from db import db_cursor
from idgen import generate_id

router = APIRouter(prefix="/api", tags=["map-files"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
# A KMZ is a zip; a small one can expand to something enormous. KML is
# verbose but not that verbose.
MAX_KML_BYTES = 60 * 1024 * 1024
MAX_FEATURES = 500

FORMATS = ("kml", "kmz", "gpx")
MEDIA_TYPES = {
    "kml": "application/vnd.google-earth.kml+xml",
    "kmz": "application/vnd.google-earth.kmz",
    "gpx": "application/gpx+xml",
}

# The environment scale in KML's aabbggrr colour order. Same colours as the
# map's legend (styles.css --zone-*), so an exported file opened in Google
# Earth reads the same as the screen it came from.
_ENV_RGB = {
    "Permissive": "2e8b57", "Semi-permissive": "d4a017", "Non-permissive": "d0392b",
    "Denied": "7a1010", "Unknown": "7f8c8d", None: "2563eb",
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """The tag without its namespace. KML ships as 2.0, 2.1, 2.2, with and
    without the gx extension, and sometimes with no namespace at all; matching
    on local names reads all of them."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name) -> Optional[str]:
    c = _child(el, name)
    if c is None or c.text is None:
        return None
    t = c.text.strip()
    return t or None


def _parse_coords(text: str) -> list:
    """KML coordinates: 'lon,lat[,alt] lon,lat[,alt] ...'."""
    out = []
    for token in (text or "").split():
        bits = token.split(",")
        if len(bits) < 2:
            continue
        try:
            out.append(geo.clean_position([float(b) for b in bits[:3]]))
        except ValueError:
            continue
    return out


def _parse_time(text) -> Optional[int]:
    """ISO 8601 -> epoch ms, or None. Accepts the trailing Z both formats use."""
    if not text:
        return None
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _clean_description(text) -> Optional[str]:
    """KML descriptions are often HTML. Kept as readable text."""
    if not text:
        return None
    t = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:8000] or None


def _kml_geometries(el) -> list:
    """(kind, geometry, times) for one geometry element, recursing into
    MultiGeometry and gx:MultiTrack."""
    name = _local(el.tag)
    if name == "Point":
        coords = _parse_coords(_text(el, "coordinates"))
        return [("point", {"type": "Point", "coordinates": coords[0]}, None)] if coords else []
    if name == "LineString":
        coords = _parse_coords(_text(el, "coordinates"))
        return [("line", {"type": "LineString", "coordinates": coords}, None)] if len(coords) >= 2 else []
    if name == "LinearRing":
        coords = _parse_coords(_text(el, "coordinates"))
        return [("area", {"type": "Polygon", "coordinates": [coords]}, None)] if len(coords) >= 3 else []
    if name == "Polygon":
        outer = _child(el, "outerBoundaryIs")
        ring = _child(outer, "LinearRing") if outer is not None else None
        coords = _parse_coords(_text(ring, "coordinates")) if ring is not None else []
        if len(coords) >= 3:
            if coords[0][:2] != coords[-1][:2]:
                coords.append(coords[0])
            return [("area", {"type": "Polygon", "coordinates": [coords]}, None)]
        return []
    if name == "Track":
        # gx:Track: parallel <when> and <gx:coord> lists, "lon lat alt".
        whens = [_parse_time(c.text) for c in el if _local(c.tag) == "when"]
        coords = []
        for c in el:
            if _local(c.tag) == "coord" and c.text:
                bits = c.text.split()
                try:
                    coords.append(geo.clean_position([float(b) for b in bits[:3]]))
                except (ValueError, IndexError):
                    coords.append(None)
        pairs = [(p, whens[i] if i < len(whens) else None)
                 for i, p in enumerate(coords) if p is not None]
        if len(pairs) < 2:
            return []
        times = [t for _, t in pairs]
        return [("line", {"type": "LineString", "coordinates": [p for p, _ in pairs]},
                 times if all(t is not None for t in times) else None)]
    if name in ("MultiGeometry", "MultiTrack"):
        out = []
        for c in el:
            out += _kml_geometries(c)
        return out
    return []


def _group(name, description, geoms) -> list:
    """Placemark geometries -> features. Lines in one placemark become one
    route (a MultiLineString, gaps kept); each area and point stays separate."""
    features = []
    lines = [(g, t) for kind, g, t in geoms if kind == "line"]
    if lines:
        if len(lines) == 1:
            geometry, times = lines[0]
        else:
            geometry = {"type": "MultiLineString",
                        "coordinates": [g["coordinates"] for g, _ in lines]}
            times = ([t for _, ts in lines for t in ts]
                     if all(ts for _, ts in lines) else None)
        features.append({"kind": "route", "name": name, "description": description,
                         "geometry": geometry, "times": times})
    areas = [g for kind, g, _ in geoms if kind == "area"]
    for i, g in enumerate(areas):
        features.append({"kind": "zone",
                         "name": name if len(areas) == 1 else f"{name} ({i + 1})",
                         "description": description, "geometry": g, "times": None})
    points = [g for kind, g, _ in geoms if kind == "point"]
    for i, g in enumerate(points):
        features.append({"kind": "location",
                         "name": name if len(points) == 1 else f"{name} ({i + 1})",
                         "description": description, "geometry": g, "times": None})
    return features


def parse_kml(data: bytes) -> list:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"That is not readable KML: {exc}")
    features = []
    for el in root.iter():
        if _local(el.tag) != "Placemark":
            continue
        name = (_text(el, "name") or "Unnamed")[:256]
        description = _clean_description(_text(el, "description"))
        geoms = []
        for c in el:
            geoms += _kml_geometries(c)
        features += _group(name, description, geoms)
    return features


def parse_gpx(data: bytes) -> list:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"That is not readable GPX: {exc}")

    def point(el):
        try:
            lat, lon = float(el.get("lat")), float(el.get("lon"))
        except (TypeError, ValueError):
            return None, None
        ele = _text(el, "ele")
        try:
            pos = geo.clean_position([lon, lat, float(ele)] if ele else [lon, lat])
        except ValueError:
            return None, None
        return pos, _parse_time(_text(el, "time"))

    features = []
    for trk in [e for e in root.iter() if _local(e.tag) == "trk"]:
        segments, times, all_timed = [], [], True
        for seg in _children(trk, "trkseg"):
            pts = [point(p) for p in _children(seg, "trkpt")]
            pts = [(p, t) for p, t in pts if p is not None]
            if len(pts) >= 2:
                segments.append([p for p, _ in pts])
                times += [t for _, t in pts]
                all_timed = all_timed and all(t is not None for _, t in pts)
        if not segments:
            continue
        geometry = ({"type": "LineString", "coordinates": segments[0]} if len(segments) == 1
                    else {"type": "MultiLineString", "coordinates": segments})
        features.append({"kind": "route", "name": (_text(trk, "name") or "Track")[:256],
                         "description": _clean_description(_text(trk, "desc") or _text(trk, "cmt")),
                         "geometry": geometry, "times": times if all_timed else None})
    for rte in [e for e in root.iter() if _local(e.tag) == "rte"]:
        pts = [point(p)[0] for p in _children(rte, "rtept")]
        pts = [p for p in pts if p is not None]
        if len(pts) >= 2:
            features.append({"kind": "route", "name": (_text(rte, "name") or "Route")[:256],
                             "description": _clean_description(_text(rte, "desc")),
                             "geometry": {"type": "LineString", "coordinates": pts}, "times": None})
    for wpt in [e for e in root.iter() if _local(e.tag) == "wpt"]:
        p, _ = point(wpt)
        if p is not None:
            features.append({"kind": "location", "name": (_text(wpt, "name") or "Waypoint")[:256],
                             "description": _clean_description(_text(wpt, "desc") or _text(wpt, "cmt")),
                             "geometry": {"type": "Point", "coordinates": p}, "times": None})
    return features


def _kml_from_kmz(data: bytes) -> bytes:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="That KMZ is not a valid zip file.")
    names = [i for i in zf.infolist() if i.filename.lower().endswith(".kml")]
    if not names:
        raise HTTPException(status_code=400, detail="That KMZ has no KML inside it.")
    # doc.kml by convention; otherwise the first one at the shallowest depth.
    names.sort(key=lambda i: (i.filename.lower() != "doc.kml", i.filename.count("/"), i.filename))
    info = names[0]
    if info.file_size > MAX_KML_BYTES:
        raise HTTPException(status_code=413, detail="The KML inside that KMZ is too large.")
    with zf.open(info) as f:
        out = f.read(MAX_KML_BYTES + 1)
    if len(out) > MAX_KML_BYTES:
        raise HTTPException(status_code=413, detail="The KML inside that KMZ is too large.")
    return out


def file_kind(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if ext in FORMATS:
        return ext
    if data[:2] == b"PK":
        return "kmz"
    head = data[:2000].lower()
    if b"<gpx" in head:
        return "gpx"
    if b"<kml" in head:
        return "kml"
    raise HTTPException(status_code=400, detail="Choose a .kml, .kmz or .gpx file.")


def parse_file(filename: str, data: bytes) -> tuple:
    """(format, features) with each feature checked and measured."""
    kind = file_kind(filename, data)
    if kind == "kmz":
        features = parse_kml(_kml_from_kmz(data))
    elif kind == "kml":
        features = parse_kml(data)
    else:
        features = parse_gpx(data)
    if not features:
        raise HTTPException(status_code=400,
                            detail="No lines, areas or points were found in that file.")
    if len(features) > MAX_FEATURES:
        raise HTTPException(status_code=400,
                            detail=f"That file has {len(features)} features; the limit is "
                                   f"{MAX_FEATURES}. Split it, or import the part you need.")
    for i, f in enumerate(features):
        f["index"] = i
        if f["kind"] == "route":
            try:
                f["geometry"] = geo.normalise_line(f["geometry"])
            except ValueError as exc:
                f["error"] = str(exc)
                continue
            f["length_m"] = round(geo.line_length_m(f["geometry"]), 1)
            f["point_count"] = geo.point_count(f["geometry"])
        elif f["kind"] == "zone":
            ring = f["geometry"]["coordinates"][0]
            if len(ring) - 1 > zones_module.MAX_RING_POINTS:
                f["error"] = (f"{len(ring) - 1} corners, over the "
                              f"{zones_module.MAX_RING_POINTS} limit for a zone")
            f["point_count"] = len(ring) - 1
        else:
            f["point_count"] = 1
    return kind, features


async def _read_upload(file: UploadFile) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")
    return data


def _store_original(cur, filename: str, data: bytes, kind: str, entity_ids: list, user: dict) -> None:
    """The file goes onto every record made from it, one copy each -- deleting
    an attachment removes its file, so a shared row would mean removing it from
    one route takes it off the other nine."""
    now = datetime.utcnow()
    rel_dir = os.path.join(str(now.year), f"{now.month:02d}")
    os.makedirs(os.path.join(UPLOAD_DIR, rel_dir), exist_ok=True)
    display = re.sub(r"[\x00-\x1f]", "", os.path.basename(filename or f"import.{kind}"))[:255]
    for entity_id in entity_ids:
        path = os.path.join(rel_dir, f"{uuid.uuid4().hex}.{kind}")
        with open(os.path.join(UPLOAD_DIR, path), "wb") as f:
            f.write(data)
        cur.execute(
            "INSERT INTO attachments (entity_id, filename, title, source_note, storage_path, "
            "        mime_type, file_size_bytes, uploaded_by, extraction_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'skipped')",
            (entity_id, display, display, "The map file this was imported from",
             path, MEDIA_TYPES[kind], len(data), user["id"]))


def _preview_feature(f: dict) -> dict:
    """What the dialog shows. The geometry goes too, thinned, so the dialog can
    draw what is about to be imported."""
    out = {k: f.get(k) for k in ("index", "kind", "name", "description", "length_m",
                                 "point_count", "error")}
    out["has_times"] = bool(f.get("times"))
    g = f["geometry"]
    out["geometry"] = (geo.simplified_line(g, 0.00005)
                       if g["type"] in ("LineString", "MultiLineString") else g)
    return out


@router.post("/map/import")
async def import_map_file(
    file: UploadFile = File(...),
    mode: str = Form(default="preview"),
    # JSON list of {index, name?, as?, environment?, travel_mode?} for commit.
    choices: str = Form(default="[]"),
    user: dict = Depends(auth.require_user),
):
    data = await _read_upload(file)
    kind, features = parse_file(file.filename, data)

    if mode == "preview":
        counts = {}
        for f in features:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        return {"format": kind, "filename": file.filename, "counts": counts,
                "features": [_preview_feature(f) for f in features],
                "environments": list(entities_module.ENVIRONMENT_VALUES),
                "travel_modes": list(entities_module.TRAVEL_MODES)}

    if mode != "commit":
        raise HTTPException(status_code=400, detail="mode must be preview or commit")
    try:
        picked = json.loads(choices or "[]")
        assert isinstance(picked, list)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="choices must be a JSON list")
    by_index = {f["index"]: f for f in features}
    made = []
    with db_cursor(commit=True) as cur:
        for choice in picked:
            f = by_index.get(choice.get("index"))
            if f is None or f.get("error"):
                continue
            name = (choice.get("name") or f["name"] or "Unnamed").strip()[:256]
            description = f.get("description")
            if f["kind"] == "route":
                entity_id = routes_module.insert_route(
                    cur, user, name=name, description=description, geometry=f["geometry"],
                    origin="imported", environment=choice.get("environment") or None,
                    travel_mode=choice.get("travel_mode") or None,
                    source_file=os.path.basename(file.filename or "")[:255] or None,
                    point_times=f.get("times"),
                    recorded_from=_iso(f["times"][0]) if f.get("times") else None,
                    recorded_until=_iso(f["times"][-1]) if f.get("times") else None)
            elif f["kind"] == "zone":
                ring = [[p[1], p[0]] for p in f["geometry"]["coordinates"][0][:-1]]
                geojson, radius_m, bounds = zones_module._geometry_from(
                    zones_module.ZoneGeometry(shape="polygon", points=ring))
                zone = zones_module.insert_zone(
                    cur, user, name=name, environment=choice.get("environment") or "Unknown",
                    shape="polygon", geojson=geojson, radius_m=None, bounds=bounds,
                    notes=description, change_note=f"Imported from {file.filename}")
                entity_id = zone["entity_id"]
            else:
                lon, lat = f["geometry"]["coordinates"][:2]
                entity_id = generate_id("location", name)
                cur.execute(
                    "INSERT INTO entities (id, entity_type, name, description, created_by) "
                    "VALUES (%s, 'location', %s, %s, %s)", (entity_id, name, description, user["id"]))
                entities_module._insert_details(cur, "location", entity_id,
                                                {"lat": lat, "lng": lon})
                entities_module._apply_location_derived_fields(cur, entity_id, None, lat, lon)
            made.append({"id": entity_id, "name": name, "entity_type": f["kind"]})
        if not made:
            raise HTTPException(status_code=400, detail="Nothing was selected to import.")
        _store_original(cur, file.filename, data, kind, [m["id"] for m in made], user)

    audit.record("map.import", user=user, object_type="file", object_label=file.filename,
                 detail={"format": kind, "created": [m["id"] for m in made]})
    return {"created": made}


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    # The Z form: what GPX readers and KML's <when> expect to see.
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _kml_coords(points) -> str:
    return " ".join(",".join(f"{v:.7f}".rstrip("0").rstrip(".") if i < 2 else f"{v:.1f}"
                             for i, v in enumerate(p)) for p in points)


def _style_id(env) -> str:
    return "env-" + re.sub(r"[^a-z]", "", (env or "none").lower())


def _kml_styles() -> str:
    out = []
    for env, rgb in _ENV_RGB.items():
        bgr = rgb[4:6] + rgb[2:4] + rgb[0:2]
        out.append(
            f'<Style id="{_style_id(env)}"><LineStyle><color>ff{bgr}</color><width>4</width></LineStyle>'
            f'<PolyStyle><color>55{bgr}</color></PolyStyle></Style>')
    return "".join(out)


def _route_placemark(route: dict) -> str:
    line = route["geometry"] if isinstance(route["geometry"], dict) else json.loads(route["geometry"])
    times = route.get("point_times")
    if isinstance(times, str):
        times = json.loads(times)
    desc = route.get("description") or ""
    meta = ", ".join(x for x in (route.get("travel_mode"), route.get("environment"),
                                 geo.format_length(route.get("length_m"))) if x)
    parts = geo.line_parts(line)
    if times and len(parts) == 1 and len(times) == len(parts[0]):
        # gx:Track keeps the time on every point, which is what makes a walked
        # route evidence of when as well as where.
        body = "<gx:Track>" + "".join(f"<when>{_iso(t)}</when>" for t in times) + "".join(
            "<gx:coord>" + " ".join(str(v) for v in p) + "</gx:coord>" for p in parts[0]) + "</gx:Track>"
    elif len(parts) == 1:
        body = f"<LineString><tessellate>1</tessellate><coordinates>{_kml_coords(parts[0])}</coordinates></LineString>"
    else:
        body = "<MultiGeometry>" + "".join(
            f"<LineString><tessellate>1</tessellate><coordinates>{_kml_coords(p)}</coordinates></LineString>"
            for p in parts) + "</MultiGeometry>"
    text = "\n\n".join(x for x in (desc, meta) if x)
    return (f"<Placemark><name>{escape(route['name'])}</name>"
            f"<description>{escape(text)}</description>"
            f"<styleUrl>#{_style_id(route.get('environment'))}</styleUrl>{body}</Placemark>")


def _zone_placemark(zone: dict) -> str:
    ring = geo.zone_ring(zone)
    bits = [zone.get("environment")]
    if zone.get("valid_until"):
        bits.append(f"until {zone['valid_until']}")
    desc = "\n\n".join(x for x in (zone.get("notes"), ", ".join(b for b in bits if b)) if x)
    return (f"<Placemark><name>{escape(zone['name'])}</name>"
            f"<description>{escape(desc)}</description>"
            f"<styleUrl>#{_style_id(zone.get('environment'))}</styleUrl>"
            f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_kml_coords(ring)}"
            f"</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")


def build_kml(title: str, routes: list, zones: list) -> bytes:
    body = "".join(_zone_placemark(z) for z in zones) + "".join(_route_placemark(r) for r in routes)
    doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">'
           f"<Document><name>{escape(title)}</name>{_kml_styles()}{body}</Document></kml>\n")
    return doc.encode("utf-8")


def build_kmz(kml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)
    return buf.getvalue()


def build_gpx(title: str, routes: list) -> bytes:
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="HUMINT Platform" xmlns="http://www.topografix.com/GPX/1/1">'
           f"<metadata><name>{escape(title)}</name></metadata>"]
    for route in routes:
        line = route["geometry"] if isinstance(route["geometry"], dict) else json.loads(route["geometry"])
        times = route.get("point_times")
        if isinstance(times, str):
            times = json.loads(times)
        out.append(f"<trk><name>{escape(route['name'])}</name>")
        if route.get("description"):
            out.append(f"<desc>{escape(route['description'])}</desc>")
        i = 0
        for part in geo.line_parts(line):
            out.append("<trkseg>")
            for p in part:
                ele = f"<ele>{p[2]}</ele>" if len(p) > 2 else ""
                t = (f"<time>{_iso(times[i])}</time>"
                     if times and i < len(times) and times[i] is not None else "")
                out.append(f'<trkpt lat="{p[1]}" lon="{p[0]}">{ele}{t}</trkpt>')
                i += 1
            out.append("</trkseg>")
        out.append("</trk>")
    out.append("</gpx>\n")
    return "".join(out).encode("utf-8")


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "map"


def _respond(fmt: str, title: str, routes: list, zones: list) -> Response:
    if fmt not in FORMATS:
        raise HTTPException(status_code=400, detail="format must be kml, kmz or gpx")
    if fmt == "gpx":
        if not routes:
            raise HTTPException(status_code=400,
                                detail="GPX carries routes only. Export areas as KML or KMZ.")
        data = build_gpx(title, routes)
    else:
        data = build_kml(title, routes, zones)
        if fmt == "kmz":
            data = build_kmz(data)
    return Response(content=data, media_type=MEDIA_TYPES[fmt], headers={
        "Content-Disposition": f'attachment; filename="{_safe_filename(title)}.{fmt}"'})


def _zone_for_export(cur, zone_id: int) -> dict:
    zone = zones_module._fetch_zone(cur, zone_id)
    return zone


@router.get("/routes/{entity_id}/export")
def export_route(entity_id: str, format: str = Query(default="kml"),
                 user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        route = routes_module.fetch_route(cur, entity_id, with_times=True)
    audit.record("export.route", user=user, object_type="entity", object_id=entity_id,
                 object_label=route["name"], detail={"format": format})
    return _respond(format, route["name"], [route], [])


@router.get("/map/zones/{zone_id}/export")
def export_zone(zone_id: int, format: str = Query(default="kml"),
                user: dict = Depends(auth.require_user)):
    with db_cursor() as cur:
        zone = _zone_for_export(cur, zone_id)
    audit.record("export.zone", user=user, object_type="entity", object_id=zone.get("entity_id"),
                 object_label=zone["name"], detail={"format": format})
    return _respond(format, zone["name"], [], [zone])


@router.get("/map/export")
def export_map(format: str = Query(default="kmz"),
               include_expired: bool = Query(default=False),
               user: dict = Depends(auth.require_user)):
    """Every live route and zone on the map in one file -- for loading the
    whole picture into ATAK or Google Earth."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT e.id FROM entities e JOIN route_details r ON r.entity_id = e.id "
            "WHERE e.is_active AND e.merged_into IS NULL ORDER BY e.name")
        routes = [routes_module.fetch_route(cur, r[0], with_times=True) for r in cur.fetchall()]
        zones = [z for z in zones_module.list_zones(include_expired=include_expired, user=user)["items"]]
    if not routes and not zones and format != "gpx":
        raise HTTPException(status_code=400, detail="There are no routes or zones on the map yet.")
    audit.record("export.map_layers", user=user, object_type="map",
                 detail={"format": format, "routes": len(routes), "zones": len(zones)})
    title = f"Map layers {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    return _respond(format, title, routes, [] if format == "gpx" else zones)
