"""Small geometry for zones, routes and the printed map.

Plain Python on GeoJSON, deliberately: the questions this app asks of a shape
are "how long", "what rectangle holds it", "is this point inside", and "give
me fewer points to draw". None of that justifies PostGIS between a user and
`docker compose up` (see the note at the top of api/zones.py).

Conventions, because mixing them up puts a route in the sea:
  * GeoJSON, which is what is stored, is [lon, lat] (optionally [lon, lat, ele]).
  * Leaflet, which is what the browser sends, is [lat, lon].
Conversion happens at the edges of the API and nowhere else.
"""

import math
from typing import Iterable, Optional

EARTH_RADIUS_M = 6_371_000.0

# One route of more than this many points is a tracker left running for a
# week or a traced coastline. The field app thins its tracks long before this.
MAX_ROUTE_POINTS = 50_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def line_parts(geometry: dict) -> list:
    """The pieces of a LineString/MultiLineString, each a list of [lon, lat(, ele)]."""
    if not geometry:
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return [part for part in coords if part]
    return []


def all_positions(geometry: dict) -> list:
    """Every [lon, lat] in a GeoJSON geometry, for bounds."""
    if not geometry:
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point":
        return [coords]
    if kind in ("LineString", "MultiPoint"):
        return list(coords)
    if kind in ("MultiLineString", "Polygon"):
        return [p for part in coords for p in part]
    if kind == "MultiPolygon":
        return [p for poly in coords for ring in poly for p in ring]
    return []


def bounds_of(positions: Iterable) -> Optional[tuple]:
    """(min_lat, min_lon, max_lat, max_lon) of [lon, lat] positions, or None."""
    lats, lons = [], []
    for p in positions:
        lons.append(float(p[0]))
        lats.append(float(p[1]))
    if not lats:
        return None
    return min(lats), min(lons), max(lats), max(lons)


def line_length_m(geometry: dict) -> float:
    total = 0.0
    for part in line_parts(geometry):
        for a, b in zip(part, part[1:]):
            total += haversine_m(a[1], a[0], b[1], b[0])
    return total


def clean_position(p) -> list:
    """[lon, lat] or [lon, lat, ele] as floats, or ValueError."""
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        raise ValueError("Each point must be [longitude, latitude]")
    lon, lat = float(p[0]), float(p[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("A point is off the map")
    if len(p) >= 3 and p[2] is not None:
        try:
            return [lon, lat, round(float(p[2]), 1)]
        except (TypeError, ValueError):
            pass
    return [lon, lat]


def latlon_to_line(points: list) -> dict:
    """Leaflet [[lat, lon], ...] -> GeoJSON LineString."""
    return {"type": "LineString",
            "coordinates": [clean_position([p[1], p[0]]) for p in points]}


def normalise_line(geometry: dict) -> dict:
    """Validate a LineString/MultiLineString and drop degenerate pieces.

    A piece needs two points to be a line. A track with a single stray fix at
    the start of a gap is common and is dropped rather than refused.
    """
    parts = []
    for part in line_parts(geometry):
        cleaned = [clean_position(p) for p in part]
        # Consecutive duplicates add nothing and confuse simplification.
        deduped = [cleaned[0]] if cleaned else []
        for p in cleaned[1:]:
            if p[:2] != deduped[-1][:2]:
                deduped.append(p)
        if len(deduped) >= 2:
            parts.append(deduped)
    if not parts:
        raise ValueError("A route needs at least two distinct points")
    count = sum(len(p) for p in parts)
    if count > MAX_ROUTE_POINTS:
        raise ValueError(f"That route has {count} points, over the {MAX_ROUTE_POINTS} limit")
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": parts[0]}
    return {"type": "MultiLineString", "coordinates": parts}


def point_count(geometry: dict) -> int:
    return sum(len(p) for p in line_parts(geometry))


# ---------------------------------------------------------------------------
# Simplification, for drawing. Never applied to what is stored.
# ---------------------------------------------------------------------------

def _perp_dist(p, a, b) -> float:
    """Distance of p from segment ab, in the same planar units (degrees,
    longitude scaled by cos(lat)) -- good enough to decide what to drop."""
    k = math.cos(math.radians(p[1]))
    px, py = p[0] * k, p[1]
    ax, ay = a[0] * k, a[1]
    bx, by = b[0] * k, b[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(points: list, tolerance_deg: float) -> list:
    """Douglas-Peucker, iterative so a 50,000-point track cannot blow the stack."""
    if len(points) < 3 or tolerance_deg <= 0:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best, index = 0.0, None
        for i in range(first + 1, last):
            d = _perp_dist(points[i], points[first], points[last])
            if d > best:
                best, index = d, i
        if index is not None and best > tolerance_deg:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def simplified_line(geometry: dict, tolerance_deg: float) -> dict:
    parts = [simplify(part, tolerance_deg) for part in line_parts(geometry)]
    if geometry.get("type") == "LineString":
        return {"type": "LineString", "coordinates": parts[0] if parts else []}
    return {"type": "MultiLineString", "coordinates": parts}


def circle_ring(lat: float, lon: float, radius_m: float, segments: int = 64) -> list:
    """A circle as a closed GeoJSON ring, for exports and the printed map,
    which have no circle primitive."""
    ring = []
    for i in range(segments + 1):
        bearing = 2 * math.pi * i / segments
        d = radius_m / EARTH_RADIUS_M
        p1, l1 = math.radians(lat), math.radians(lon)
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(bearing))
        l2 = l1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(p1),
                             math.cos(d) - math.sin(p1) * math.sin(p2))
        ring.append([round(math.degrees(l2), 7), round(math.degrees(p2), 7)])
    return ring


def zone_ring(zone: dict) -> list:
    """A zone's outline as a GeoJSON ring, whatever shape it was drawn as."""
    geometry = zone["geometry"]
    if zone.get("shape") == "circle":
        c = geometry["coordinates"]
        return circle_ring(c[1], c[0], zone.get("radius_m") or 0)
    return geometry["coordinates"][0]


def format_length(metres: Optional[float]) -> str:
    if metres is None:
        return ""
    if metres < 1000:
        return f"{metres:.0f} m"
    return f"{metres / 1000:.2f} km" if metres < 10_000 else f"{metres / 1000:.1f} km"
