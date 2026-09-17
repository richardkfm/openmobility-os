"""Metric geometry helpers — the small toolkit every spatial computation shares.

OpenMobility OS has to do real distance and area arithmetic for an arbitrary
municipality anywhere on Earth, so nothing here may assume a UTM zone, a
country, or a projected CRS. Everything is anchored on the workspace centre
instead: an azimuthal-equidistant projection through that point gives true
metres nearby, whichever city the workspace happens to describe.

The runtime carries ``pyproj`` and the standard library only — no shapely, no
numpy, no rtree — so the polygon predicates below are hand-rolled. They are
deliberately pure (no Django, no I/O) so they can be unit-tested without a
database, and they live here rather than inside one consumer because three
different modules need the same few primitives.
"""

from __future__ import annotations

from math import atan2, pi

from pyproj import Transformer


def _aeqd_proj(center_lonlat) -> str:
    lon, lat = center_lonlat
    return (
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
        "+datum=WGS84 +units=m +no_defs"
    )


def make_projector(center_lonlat):
    """Return a ``(lon, lat) -> (x, y)`` transform in metres about the centre.

    Uses an azimuthal-equidistant projection anchored at the workspace centre
    so distances near that centre are in true metres regardless of country —
    no hard-coded UTM zone, no Germany assumption.
    """
    transformer = Transformer.from_crs(
        "EPSG:4326", _aeqd_proj(center_lonlat), always_xy=True
    )
    return transformer.transform


def make_inverse_projector(center_lonlat):
    """Return the ``(x, y) -> (lon, lat)`` inverse of :func:`make_projector`."""
    transformer = Transformer.from_crs(
        _aeqd_proj(center_lonlat), "EPSG:4326", always_xy=True
    )
    return transformer.transform


def polygon_area_m2(ring_xy) -> float:
    """Area of a projected ring in square metres, by the shoelace formula.

    Winding order is irrelevant — the result is always non-negative — so
    callers can subtract interior rings without tracking orientation.
    """
    ring = list(ring_xy or [])
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def point_in_ring(x: float, y: float, ring_xy) -> bool:
    """Ray-casting point-in-polygon test against a single projected ring.

    A point exactly on an edge may fall either way; callers that scatter points
    inside a shape do not care, and nothing here depends on the boundary case.
    """
    ring = list(ring_xy or [])
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            # x of the edge at height y; the point is left of it -> one crossing.
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def longest_edge_bearing(ring_xy) -> float:
    """Axis of the ring's longest edge, in radians within ``[0, pi)``.

    Used to align a generated grid to the shape it fills — a car park drawn in
    rows parallel to its own long side reads as a car park; one drawn on a
    north-south grid reads as noise.

    The result is an *axis*, not a direction: a grid rotated by theta and one
    rotated by theta + pi are the same grid, so the angle is folded into a half
    turn. Without that, walking a ring clockwise instead of anticlockwise would
    rotate every generated row by 180 degrees for no reason.
    """
    ring = list(ring_xy or [])
    if len(ring) < 2:
        return 0.0
    best_len2 = -1.0
    best = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1]
        dx = x2 - x1
        dy = y2 - y1
        length2 = dx * dx + dy * dy
        if length2 > best_len2:
            best_len2 = length2
            best = atan2(dy, dx)
    return best % pi
