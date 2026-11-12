"""Is a point inside a zone? — for the worker (outside events).

A copy of the geometry in api/zones.py: the worker and the API are separate
programs (and containers) and share no code. tests/test_outside_events.py
checks the two agree on the same points, so they cannot drift apart quietly.
"""
import json
import math

_EDGE_EPSILON = 1e-7


def _on_segment(lat, lon, x1, y1, x2, y2) -> bool:
    """Is the point on this edge, to within a hair?

    Ray casting gives an arbitrary answer for a point exactly on the boundary,
    and "arbitrary" is not something to hand an analyst asking whether an
    address is inside a cordon. It happens for real: somebody drops a zone
    corner on a junction and later records a Location at the same junction.
    On the line counts as inside.
    """
    cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
    if abs(cross) > _EDGE_EPSILON:
        return False
    # Collinear with the edge -- now check it is actually between the ends
    # rather than out along the same line.
    return (min(x1, x2) - _EDGE_EPSILON <= lon <= max(x1, x2) + _EDGE_EPSILON
            and min(y1, y2) - _EDGE_EPSILON <= lat <= max(y1, y2) + _EDGE_EPSILON)


def _point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray casting, with the boundary counted as inside.

    `ring` is GeoJSON order, [[lon, lat], ...]. A horizontal ray runs east
    from the point and crossings of the ring are counted; odd means inside.
    The `(y1 > lat) != (y2 > lat)` test is what stops a vertex exactly level
    with the ray being counted twice — the classic way this algorithm is got
    wrong.
    """
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        if _on_segment(lat, lon, x1, y1, x2, y2):
            return True
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lon < x_at:
                inside = not inside
    return inside


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def zone_contains(zone: dict, lat: float, lon: float) -> bool:
    """Is this point inside this zone? The bounding box is checked first."""
    if not (zone["min_lat"] <= lat <= zone["max_lat"]
            and zone["min_lon"] <= lon <= zone["max_lon"]):
        return False
    geometry = zone["geometry"]
    if isinstance(geometry, str):
        geometry = json.loads(geometry)
    if zone["shape"] == "circle":
        centre = geometry["coordinates"]
        return _haversine_m(lat, lon, centre[1], centre[0]) <= (zone["radius_m"] or 0)
    return _point_in_ring(lat, lon, geometry["coordinates"][0])
