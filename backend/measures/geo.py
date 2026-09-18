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

from math import atan2, cos, floor, hypot, pi, radians

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


def line_length_m(geometry) -> float | None:
    """Length of a GeoJSON ``LineString`` / ``MultiLineString`` in metres.

    Works straight off lon/lat, using a local equirectangular approximation
    around the line's own mean latitude. That is accurate to well under a
    percent at street scale and correct anywhere on Earth, which a fixed
    degrees-to-metres constant would not be — and it saves projecting a whole
    city's street network just to measure it.

    Returns ``None`` for anything that is not a line, so a caller can tell "zero
    metres long" from "not a line at all".

    (``connectors/osm_connector.py`` keeps its own copy of this on purpose: a
    connector must not import from the measures app.)
    """
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "MultiLineString":
        parts = [
            line_length_m({"type": "LineString", "coordinates": part}) for part in coords
        ]
        known = [p for p in parts if p is not None]
        return round(sum(known), 1) if known else None
    if gtype != "LineString" or len(coords) < 2:
        return None
    lats = [c[1] for c in coords if len(c) >= 2]
    if not lats:
        return None
    mean_lat_rad = radians(sum(lats) / len(lats))
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * cos(mean_lat_rad)
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        if len(a) < 2 or len(b) < 2:
            continue
        dx = (b[0] - a[0]) * m_per_deg_lon
        dy = (b[1] - a[1]) * m_per_deg_lat
        total += hypot(dx, dy)
    return round(total, 1)


def iter_linestrings(geometry):
    """Yield coordinate lists for ``LineString`` / ``MultiLineString`` geometries.

    Anything else yields nothing, so a caller can loop over a mixed collection
    without type-checking each feature first.
    """
    if not geometry:
        return
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "LineString":
        yield coords
    elif gtype == "MultiLineString":
        for line in coords:
            yield line


def seg_dist2(px, py, x1, y1, x2, y2):
    """Squared distance from point ``(px, py)`` to segment ``(x1,y1)-(x2,y2)``.

    Squared, because every caller compares distances rather than reporting
    them, and a square root per candidate segment is the one avoidable cost in
    a nearest-neighbour sweep over a whole street network.
    """
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cx = x1 + t * dx
    cy = y1 + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


class SegmentGrid:
    """Uniform grid index over projected line segments for nearest-segment search.

    Each segment is registered into every cell its bounding box — inflated by
    the snap radius — touches. A query point therefore only has to look at the
    single cell it falls in: any segment within ``snap_m`` of the point is
    guaranteed to have been registered there.

    The index does **not** enforce the radius itself. :meth:`nearest` returns
    the closest segment it found along with its distance, and the caller must
    compare that distance against its own threshold — a candidate can be
    registered in a cell and still lie further away than ``snap_m``.
    """

    def __init__(self, snap_m):
        self.cell = max(snap_m * 2.0, 50.0)
        self.snap_m = snap_m
        self.cells: dict[tuple[int, int], list] = {}

    def _key(self, x, y):
        return (floor(x / self.cell), floor(y / self.cell))

    def add_segment(self, ref, x1, y1, x2, y2):
        pad = self.snap_m
        min_cx = floor((min(x1, x2) - pad) / self.cell)
        max_cx = floor((max(x1, x2) + pad) / self.cell)
        min_cy = floor((min(y1, y2) - pad) / self.cell)
        max_cy = floor((max(y1, y2) + pad) / self.cell)
        seg = (ref, x1, y1, x2, y2)
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                self.cells.setdefault((cx, cy), []).append(seg)

    def add_line(self, ref, points_xy):
        """Register every segment of an already-projected line under one ref."""
        added = False
        for a, b in zip(points_xy, points_xy[1:]):
            self.add_segment(ref, a[0], a[1], b[0], b[1])
            added = True
        return added

    def nearest(self, px, py):
        """Return ``(ref, distance_m)`` of the nearest segment, or ``(None, inf)``."""
        candidates = self.cells.get(self._key(px, py))
        if not candidates:
            return None, float("inf")
        best_ref = None
        best_d2 = float("inf")
        for ref, x1, y1, x2, y2 in candidates:
            d2 = seg_dist2(px, py, x1, y1, x2, y2)
            if d2 < best_d2:
                best_d2 = d2
                best_ref = ref
        return best_ref, best_d2 ** 0.5
