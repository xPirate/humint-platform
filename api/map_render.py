"""The printed map: tiles and the case file's shapes, flattened to a picture.

Used by "Print map" on the Map page and by the map page of a target package
or dossier. Server-side, rather than a screenshot of the browser, for two
reasons: the package is built on the server and has no browser to ask, and a
browser cannot hand back a canvas painted with another site's tiles.

How it works:

  1. Pick the deepest zoom at which the area fits the image.
  2. Fetch the tiles that cover it -- from a downloaded pack when there is one
     (offline maps work offline here too), otherwise live from the source's
     own server unless MAP_DOWNLOAD_ENABLED=false says this machine must never
     reach out. A tile that cannot be had is drawn as plain ground with a grid,
     and the page says how many were missing rather than pretending.
  3. Draw zones, routes and Location pins on top, at twice the size and scaled
     down, so lines and labels are smooth in print.

Web Mercator, north up, like every slippy map; the scale bar is computed for
the centre of the picture and the page says so.
"""

import io
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

import geometry as geo
import maptiles

TILE = 256
SS = 2                        # supersampling for the vector layers
MAX_TILES = 160               # one picture; a pack download is the tool for more
LIVE_FETCH = os.environ.get("MAP_DOWNLOAD_ENABLED", "true").lower() == "true"
USER_AGENT = os.environ.get(
    "MAP_TILE_USER_AGENT",
    "humint-platform map printer (set MAP_TILE_USER_AGENT in .env)")
TIMEOUT = float(os.environ.get("MAP_TILE_TIMEOUT_SECONDS", "8"))

# Print colours for the environment scale: the light palette's values, which
# hold up on paper and over a pale basemap. Matches the KML export.
ENV_HEX = {
    "Permissive": "#2e8b57", "Semi-permissive": "#d4a017", "Non-permissive": "#d0392b",
    "Denied": "#7a1010", "Unknown": "#7f8c8d",
}
ROUTE_HEX = "#1d4ed8"
PIN_HEX = "#5b6672"           # a Location nobody has assessed

_FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _font(size: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgb(hex_colour: str) -> tuple:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def world_px(lat: float, lon: float, z: int) -> tuple:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = TILE * (1 << z)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def choose_zoom(bbox: tuple, width: int, height: int, min_zoom=0, max_zoom=18,
                pad: int = 40) -> int:
    min_lat, min_lon, max_lat, max_lon = bbox
    for z in range(max_zoom, min_zoom - 1, -1):
        x0, y0 = world_px(max_lat, min_lon, z)
        x1, y1 = world_px(min_lat, max_lon, z)
        if (x1 - x0) <= width - 2 * pad and (y1 - y0) <= height - 2 * pad:
            return z
    return min_zoom


def metres_per_pixel(lat: float, z: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (1 << z)


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------

def _source(cur, source_id: Optional[int]) -> Optional[dict]:
    if source_id:
        cur.execute("SELECT id, url_template, subdomains, min_zoom, max_zoom, tile_format, "
                    "attribution, name FROM map_sources WHERE id = %s", (source_id,))
    else:
        cur.execute("SELECT id, url_template, subdomains, min_zoom, max_zoom, tile_format, "
                    "attribution, name FROM map_sources WHERE is_active "
                    "ORDER BY sort_order, id LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(("id", "url_template", "subdomains", "min_zoom", "max_zoom",
                     "tile_format", "attribution", "name"), row))


def _pack_paths(cur, source_id: int, z: int) -> list:
    cur.execute(
        "SELECT file_path FROM map_packs WHERE source_id = %s AND status IN ('done', 'downloading') "
        "AND file_path IS NOT NULL AND %s BETWEEN min_zoom AND max_zoom ORDER BY id DESC",
        (source_id, z))
    return [r[0] for r in cur.fetchall()]


def _live_tile(source: dict, z: int, x: int, y: int, state: dict) -> Optional[bytes]:
    # state["dead"]: one connection failure and the rest of this picture is
    # drawn without asking again. A machine with no route out would otherwise
    # spend minutes timing out tile by tile before printing a blank grid.
    if not LIVE_FETCH or not source.get("url_template") or state.get("dead"):
        return None
    url = source["url_template"]
    subs = source.get("subdomains") or ""
    if "{s}" in url:
        url = url.replace("{s}", subs[(x + y) % len(subs)] if subs else "a")
    url = url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    try:
        resp = _session.get(url, timeout=TIMEOUT)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except (requests.ConnectionError, requests.Timeout):
        state["dead"] = True
    except requests.RequestException:
        pass
    return None


def _blank_tile() -> Image.Image:
    tile = Image.new("RGB", (TILE, TILE), (238, 240, 236))
    d = ImageDraw.Draw(tile)
    for i in range(0, TILE, 64):
        d.line([(i, 0), (i, TILE)], fill=(224, 227, 222))
        d.line([(0, i), (TILE, i)], fill=(224, 227, 222))
    return tile


def _compose_basemap(cur, source, z, left, top, width, height) -> tuple:
    """(image, tiles_wanted, tiles_missing, offline_only)."""
    base = Image.new("RGB", (width, height), (238, 240, 236))
    if source is None:
        return base, 0, 0, True
    n = 1 << z
    tx0, ty0 = int(left // TILE), int(top // TILE)
    tx1, ty1 = int((left + width - 1) // TILE), int((top + height - 1) // TILE)
    coords = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)
              if 0 <= ty < n][:MAX_TILES]
    paths = _pack_paths(cur, source["id"], z)
    live_state = {}

    def fetch(c):
        tx, ty = c
        x = tx % n                      # wrap across the antimeridian
        for path in paths:
            data = maptiles._read_tile(path, z, x, ty)
            if data is not None:
                return c, bytes(data)
        return c, _live_tile(source, z, x, ty, live_state)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, coords))
    missing = 0
    blank = _blank_tile()
    for (tx, ty), data in results:
        img = None
        if data:
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:
                img = None
        if img is None:
            missing += 1
            img = blank
        base.paste(img, (int(tx * TILE - left), int(ty * TILE - top)))
    return base, len(coords), missing, not paths


# ---------------------------------------------------------------------------
# What to draw
# ---------------------------------------------------------------------------

def gather_layers(cur, bbox: tuple, *, entity_ids: Optional[set] = None,
                  zones=True, routes=True, locations=True, include_expired=True) -> dict:
    """Shapes and pins overlapping the box. With entity_ids, only those."""
    min_lat, min_lon, max_lat, max_lon = bbox
    out = {"zones": [], "routes": [], "locations": []}
    ids = list(entity_ids) if entity_ids is not None else None
    filt = " AND e.id = ANY(%s)" if ids is not None else ""
    if zones:
        cur.execute(
            f"""
            SELECT e.id, e.name, z.environment, z.shape, z.geometry, z.radius_m, z.valid_until,
                   (z.valid_until IS NOT NULL AND z.valid_until <= now())
            FROM map_zones z JOIN entities e ON e.id = z.entity_id
            WHERE e.is_active AND e.merged_into IS NULL
              AND z.max_lat >= %s AND z.min_lat <= %s AND z.max_lon >= %s AND z.min_lon <= %s
              {filt}
            ORDER BY z.created_at
            """, [min_lat, max_lat, min_lon, max_lon] + ([ids] if ids is not None else []))
        for r in cur.fetchall():
            if r[7] and not include_expired:
                continue
            g = r[4] if isinstance(r[4], dict) else json.loads(r[4])
            out["zones"].append({"id": r[0], "name": r[1], "environment": r[2], "shape": r[3],
                                 "geometry": g, "radius_m": r[5], "expired": bool(r[7])})
    if routes:
        cur.execute(
            f"""
            SELECT e.id, e.name, r.environment, r.geometry, r.origin, r.length_m
            FROM route_details r JOIN entities e ON e.id = r.entity_id
            WHERE e.is_active AND e.merged_into IS NULL
              AND r.max_lat >= %s AND r.min_lat <= %s AND r.max_lon >= %s AND r.min_lon <= %s
              {filt}
            ORDER BY e.created_at
            """, [min_lat, max_lat, min_lon, max_lon] + ([ids] if ids is not None else []))
        for r in cur.fetchall():
            g = r[3] if isinstance(r[3], dict) else json.loads(r[3])
            out["routes"].append({"id": r[0], "name": r[1], "environment": r[2],
                                  "geometry": g, "origin": r[4], "length_m": r[5]})
    if locations:
        cur.execute(
            f"""
            SELECT e.id, e.name, l.lat, l.lng, l.environment
            FROM location_details l JOIN entities e ON e.id = l.entity_id
            WHERE e.is_active AND e.merged_into IS NULL AND l.lat IS NOT NULL AND l.lng IS NOT NULL
              AND l.lat BETWEEN %s AND %s AND l.lng BETWEEN %s AND %s
              {filt}
            ORDER BY e.name
            """, [min_lat, max_lat, min_lon, max_lon] + ([ids] if ids is not None else []))
        out["locations"] = [{"id": r[0], "name": r[1], "lat": r[2], "lng": r[3],
                             "environment": r[4]} for r in cur.fetchall()]
    return out


def bounds_of_entities(cur, entity_ids: list) -> Optional[tuple]:
    """The box holding these records' shapes and pins, or None."""
    if not entity_ids:
        return None
    pts = []
    cur.execute("SELECT min_lat, min_lon, max_lat, max_lon FROM map_zones WHERE entity_id = ANY(%s) "
                "UNION ALL SELECT min_lat, min_lon, max_lat, max_lon FROM route_details "
                "WHERE entity_id = ANY(%s)", (entity_ids, entity_ids))
    for a, b, c, d in cur.fetchall():
        pts += [(a, b), (c, d)]
    cur.execute("SELECT lat, lng FROM location_details WHERE entity_id = ANY(%s) "
                "AND lat IS NOT NULL AND lng IS NOT NULL", (entity_ids,))
    pts += [(r[0], r[1]) for r in cur.fetchall()]
    if not pts:
        return None
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return min(lats), min(lons), max(lats), max(lons)


def pad_bbox(bbox: tuple, fraction: float = 0.12, min_span_deg: float = 0.004) -> tuple:
    """Room around the edges, and never so tight that a single pin is a
    rooftop: the smallest box is a few hundred metres across."""
    min_lat, min_lon, max_lat, max_lon = bbox
    dlat = max(max_lat - min_lat, min_span_deg)
    dlon = max(max_lon - min_lon, min_span_deg)
    clat, clon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
    dlat *= 1 + 2 * fraction
    dlon *= 1 + 2 * fraction
    return clat - dlat / 2, clon - dlon / 2, clat + dlat / 2, clon + dlon / 2


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _dashed(draw, pts, fill, width, dash=14, gap=10):
    """PIL has no dashed line; walk the polyline laying down dashes."""
    on, remaining = True, dash
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg == 0:
            continue
        pos = 0.0
        while pos < seg:
            step = min(remaining, seg - pos)
            if on:
                t0, t1 = pos / seg, (pos + step) / seg
                draw.line([(x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0),
                           (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)], fill=fill, width=width)
            pos += step
            remaining -= step
            if remaining <= 0:
                on = not on
                remaining = dash if on else gap


def _label(draw, placed, text, x, y, font, colour=(20, 24, 22)):
    """A name with a white halo, skipped if it would sit on another label."""
    if not text:
        return
    text = text if len(text) <= 40 else text[:39] + "…"
    box = draw.textbbox((x, y), text, font=font, stroke_width=3 * SS // 2)
    for b in placed:
        if not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]):
            return
    placed.append(box)
    draw.text((x, y), text, font=font, fill=colour, stroke_width=3 * SS // 2,
              stroke_fill=(255, 255, 255))


def render(cur, bbox: tuple, width: int, height: int, *, source_id=None,
           entity_ids: Optional[set] = None, highlight: Optional[set] = None,
           zones=True, routes=True, locations=True, labels=True,
           include_expired=True, fit_exact: bool = False) -> tuple:
    """(PIL image, meta). `bbox` is (min_lat, min_lon, max_lat, max_lon).

    With fit_exact, the box is the view the analyst was looking at and is
    filled edge to edge; otherwise it is the content to fit, with padding.
    """
    source = _source(cur, source_id)
    min_zoom = source["min_zoom"] if source else 0
    max_zoom = min(source["max_zoom"] if source else 18, 18)
    z = choose_zoom(bbox, width, height, min_zoom, max_zoom, pad=0 if fit_exact else 40)

    cx, cy = world_px((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, z)
    left, top = cx - width / 2, cy - height / 2

    base, wanted, missing, offline = _compose_basemap(cur, source, z, left, top, width, height)

    # The area actually on the picture, which is what the layers are fetched
    # for -- a print fills the page, so it shows more than the box asked for.
    def unproject(px, py):
        n = TILE * (1 << z)
        lon = px / n * 360.0 - 180.0
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n))))
        return lat, lon
    north, west = unproject(left, top)
    south, east = unproject(left + width, top + height)
    view = (south, west, north, east)

    layers = gather_layers(cur, view, entity_ids=entity_ids, zones=zones, routes=routes,
                           locations=locations, include_expired=include_expired)
    highlight = highlight or set()

    over = Image.new("RGBA", (width * SS, height * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    # Sized for paper: the picture is printed at roughly 150-180 dpi, so
    # screen-sized type would come out at four or five points.
    font = _font(15 * SS)
    small = _font(13 * SS)
    placed = []

    def px(lon, lat):
        x, y = world_px(lat, lon, z)
        return (x - left) * SS, (y - top) * SS

    for zone in layers["zones"]:
        colour = _rgb(ENV_HEX.get(zone["environment"], ENV_HEX["Unknown"]))
        ring = [px(p[0], p[1]) for p in geo.zone_ring(zone)]
        if len(ring) < 3:
            continue
        alpha = 35 if zone["expired"] else 70
        d.polygon(ring, fill=colour + (alpha,))
        w = (5 if zone["id"] in highlight else 3) * SS
        if zone["expired"]:
            _dashed(d, ring, colour + (200,), w)
        else:
            d.line(ring, fill=colour + (235,), width=w, joint="curve")
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        if labels:
            _label(d, placed, zone["name"] + (" (ended)" if zone["expired"] else ""),
                   sum(xs) / len(xs) - 30 * SS, sum(ys) / len(ys) - 6 * SS, font, colour)

    for route in layers["routes"]:
        colour = _rgb(ENV_HEX.get(route["environment"], ROUTE_HEX)) if route["environment"] else _rgb(ROUTE_HEX)
        w = (7 if route["id"] in highlight else 5) * SS
        parts = [[px(p[0], p[1]) for p in part] for part in geo.line_parts(route["geometry"])]
        for part in parts:
            if len(part) < 2:
                continue
            # A white casing first, so the line reads over busy imagery.
            d.line(part, fill=(255, 255, 255, 220), width=w + 3 * SS, joint="curve")
            if route["origin"] == "drawn":
                _dashed(d, part, colour + (255,), w, dash=16 * SS, gap=10 * SS)
            else:
                d.line(part, fill=colour + (255,), width=w, joint="curve")
        if parts and parts[0]:
            sx, sy = parts[0][0]
            r = 6 * SS
            d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 255, 255, 255), outline=colour + (255,), width=3 * SS)
            ex, ey = parts[-1][-1]
            d.rectangle([ex - r, ey - r, ex + r, ey + r], fill=colour + (255,), outline=(255, 255, 255, 255), width=2 * SS)
            if labels:
                mid = parts[0][len(parts[0]) // 2]
                _label(d, placed, route["name"], mid[0] + 8 * SS, mid[1] - 18 * SS, font, colour)

    for loc in layers["locations"]:
        colour = _rgb(ENV_HEX.get(loc["environment"], PIN_HEX)) if loc["environment"] else _rgb(PIN_HEX)
        x, y = px(loc["lng"], loc["lat"])
        r = (8 if loc["id"] in highlight else 6) * SS
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour + (255,), outline=(255, 255, 255, 255), width=2 * SS)
        if labels:
            _label(d, placed, loc["name"], x + r + 3 * SS, y - 7 * SS, small)

    over = over.resize((width, height), Image.LANCZOS)
    img = base.convert("RGBA")
    img.alpha_composite(over)
    img = img.convert("RGB")
    _scale_and_north(img, (bbox[0] + bbox[2]) / 2, z)

    meta = {
        "zoom": z, "bbox": view, "tiles": wanted, "tiles_missing": missing,
        "source": source["name"] if source else None,
        "attribution": source["attribution"] if source else None,
        "offline_only": offline and not LIVE_FETCH,
        "counts": {k: len(v) for k, v in layers.items()},
        "metres_per_pixel": metres_per_pixel((bbox[0] + bbox[2]) / 2, z),
    }
    return img, meta


def _nice_length(max_m: float) -> float:
    """The longest round distance that fits in max_m."""
    best = 5
    for m in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000,
              10000, 20000, 25000, 50000, 100000, 200000, 500000, 1000000):
        if m > max_m:
            break
        best = m
    return best


def _scale_and_north(img: Image.Image, lat: float, z: int) -> None:
    d = ImageDraw.Draw(img)
    w, h = img.size
    mpp = metres_per_pixel(lat, z)
    length_m = _nice_length(mpp * w / 5)
    bar = length_m / mpp
    font = _font(14)
    label = f"{int(length_m)} m" if length_m < 1000 else f"{length_m / 1000:g} km"
    x0, y0 = 14, h - 30
    d.rectangle([x0 - 8, y0 - 18, x0 + bar + 10, y0 + 14], fill=(255, 255, 255))
    d.rectangle([x0, y0, x0 + bar, y0 + 6], fill=(20, 24, 22))
    d.rectangle([x0 + bar / 2, y0 + 1, x0 + bar - 1, y0 + 5], fill=(255, 255, 255))
    d.text((x0, y0 - 16), label, font=font, fill=(20, 24, 22))
    # North arrow, top right. Web Mercator is always north-up.
    ax, ay = w - 30, 18
    d.rectangle([ax - 16, ay - 8, ax + 16, ay + 44], fill=(255, 255, 255))
    d.polygon([(ax, ay), (ax - 9, ay + 24), (ax, ay + 18), (ax + 9, ay + 24)], fill=(20, 24, 22))
    d.text((ax - 4, ay + 26), "N", font=font, fill=(20, 24, 22))


def legend_items(meta: dict) -> list:
    """(label, hex, kind) for what is actually on this picture."""
    items = [(env, ENV_HEX[env], "fill") for env in
             ("Permissive", "Semi-permissive", "Non-permissive", "Denied", "Unknown")]
    if meta["counts"].get("routes"):
        items += [("Route (walked or imported)", ROUTE_HEX, "line"),
                  ("Route (drawn — a plan)", ROUTE_HEX, "dash")]
    return items


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
