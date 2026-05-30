"""Accident-density aggregation: snap accident points onto a street network.

This is the engine behind the map's "Density lines" view and the cycling
infrastructure gap analysis. It takes raw accident point features and a street
network (both GeoJSON) and accumulates a severity-weighted score per street so
the map can colour whole streets blue→red by accident density — the same idea
as the German Unfallatlas, but city-agnostic: the metric projection is derived
from the workspace centre, so it works for any municipality on Earth.

No shapely/numpy/rtree are available in the runtime; only ``pyproj`` (for a
local metric CRS) and the Python standard library. Snapping is a hand-rolled
point-to-segment nearest search accelerated by a uniform grid index, so the
cost stays manageable even for the thousands of points a real Unfallatlas
import produces.

Severity weighting reuses the project-wide convention (fatal×3, serious×2,
minor×1) so the score means the same thing here as in the measures engine.
"""

from __future__ import annotations

from math import floor

from pyproj import Transformer

# Same weights the rest of the codebase uses (measures.rules.safety,
# the map heatmap). Kept local to avoid a hard cross-module import, but
# intentionally identical so the score is comparable across features.
SEVERITY_WEIGHT = {"fatal": 3, "serious": 2, "minor": 1}

DEFAULT_SNAP_M = 25.0
DEFAULT_GAP_M = 20.0
DEFAULT_MIN_SCORE = 3


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _make_projector(center_lonlat):
    """Return a (lon, lat) → (x, y) metres transformer centred on the workspace.

    Uses an azimuthal-equidistant projection anchored at the workspace centre
    so distances near that centre are in true metres regardless of country —
    no hard-coded UTM zone, no Germany assumption.
    """
    lon, lat = center_lonlat
    aeqd = (
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
        "+datum=WGS84 +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
    return transformer.transform


def _iter_linestrings(geometry):
    """Yield coordinate lists for LineString / MultiLineString geometries."""
    if not geometry:
        return
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "LineString":
        yield coords
    elif gtype == "MultiLineString":
        for line in coords:
            yield line


def _point_coords(geometry):
    if not geometry or geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates") or []
    if len(coords) < 2:
        return None
    return coords[0], coords[1]


def _seg_dist2(px, py, x1, y1, x2, y2):
    """Squared distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
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


# --------------------------------------------------------------------------- #
# Grid spatial index
# --------------------------------------------------------------------------- #
class _SegmentGrid:
    """Uniform grid index over projected line segments for nearest-segment search.

    Each segment is registered into every cell its bounding box — inflated by
    the snap radius — touches. A query point therefore only has to look at the
    single cell it falls in: any segment within ``snap_m`` of the point is
    guaranteed to have been registered there.
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

    def nearest(self, px, py):
        """Return (ref, distance_m) of the nearest segment, or (None, inf)."""
        candidates = self.cells.get(self._key(px, py))
        if not candidates:
            return None, float("inf")
        best_ref = None
        best_d2 = float("inf")
        for ref, x1, y1, x2, y2 in candidates:
            d2 = _seg_dist2(px, py, x1, y1, x2, y2)
            if d2 < best_d2:
                best_d2 = d2
                best_ref = ref
        return best_ref, best_d2 ** 0.5


# --------------------------------------------------------------------------- #
# Street indexing
# --------------------------------------------------------------------------- #
def _street_name(props):
    for key in ("name", "street_name", "ref"):
        val = props.get(key)
        if val:
            return str(val)
    return ""


def _index_streets(streets, transform, snap_m):
    """Project street features and build a grid index keyed by street index.

    Returns (grid, street_meta) where street_meta[i] holds the original
    geometry + display name for the i-th street feature.
    """
    grid = _SegmentGrid(snap_m)
    meta = []
    for idx, feat in enumerate(streets):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        projected_lines = []
        has_segment = False
        for line in _iter_linestrings(geom):
            pts = [transform(c[0], c[1]) for c in line if len(c) >= 2]
            projected_lines.append(pts)
            for a, b in zip(pts, pts[1:]):
                grid.add_segment(idx, a[0], a[1], b[0], b[1])
                has_segment = True
        if not has_segment:
            meta.append(None)
            continue
        meta.append(
            {
                "geometry": geom,
                "name": _street_name(props),
                "projected_lines": projected_lines,
            }
        )
    return grid, meta


# --------------------------------------------------------------------------- #
# Accident filtering
# --------------------------------------------------------------------------- #
def _accident_modes(props):
    modes = props.get("involved_modes") or []
    if isinstance(modes, str):
        modes = [modes]
    return modes


def _filter_accidents(accidents, *, years, severities, modes):
    """Pre-filter accident features by year / severity / involved mode."""
    years = {int(y) for y in years} if years else None
    severities = set(severities) if severities else None
    modes = set(modes) if modes else None

    out = []
    for feat in accidents:
        props = feat.get("properties") or {}
        sev = props.get("severity", "minor")
        if severities is not None and sev not in severities:
            continue
        if years is not None:
            y = props.get("year")
            try:
                if y is None or int(y) not in years:
                    continue
            except (TypeError, ValueError):
                continue
        if modes is not None:
            if not (modes & set(_accident_modes(props))):
                continue
        out.append(feat)
    return out


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def aggregate_by_street(accidents, streets, *, center_lonlat, snap_m=DEFAULT_SNAP_M):
    """Snap accidents to nearest street and accumulate weighted scores.

    Returns (per_street, contributing, unsnapped) where per_street maps a
    street index → aggregate dict. Pure function; no Django dependency.
    """
    transform = _make_projector(center_lonlat)
    grid, meta = _index_streets(streets, transform, snap_m)

    per_street: dict[int, dict] = {}
    contributing = 0
    unsnapped = 0

    for feat in accidents:
        coords = _point_coords(feat.get("geometry"))
        if coords is None:
            unsnapped += 1
            continue
        px, py = transform(coords[0], coords[1])
        idx, dist = grid.nearest(px, py)
        if idx is None or dist > snap_m:
            unsnapped += 1
            continue

        props = feat.get("properties") or {}
        sev = props.get("severity", "minor")
        weight = SEVERITY_WEIGHT.get(sev, 1)

        agg = per_street.get(idx)
        if agg is None:
            agg = {
                "accident_count": 0,
                "severity_score": 0,
                "fatal": 0,
                "serious": 0,
                "minor": 0,
                "by_mode": {},
            }
            per_street[idx] = agg
        agg["accident_count"] += 1
        agg["severity_score"] += weight
        if sev in ("fatal", "serious", "minor"):
            agg[sev] += 1
        for mode in _accident_modes(props):
            agg["by_mode"][mode] = agg["by_mode"].get(mode, 0) + 1
        contributing += 1

    return per_street, meta, contributing, unsnapped


def compute_density_lines(
    accidents,
    streets,
    *,
    center_lonlat,
    years=None,
    severities=None,
    modes=None,
    snap_m=DEFAULT_SNAP_M,
):
    """Build a coloured-LineString FeatureCollection for the density view.

    Each output feature is an original street geometry that received at least
    one matching accident, carrying the aggregate score and breakdown in its
    properties. A ``metadata`` block exposes the method and filter inputs so
    the result is transparent (CLAUDE.md principle 3).
    """
    filtered = _filter_accidents(
        accidents, years=years, severities=severities, modes=modes
    )

    if not streets:
        return {
            "type": "FeatureCollection",
            "features": [],
            "metadata": {
                "method": "none",
                "reason": "no_streets",
                "max_score": 0,
                "contributing_accidents": 0,
                "unsnapped_accidents": len(filtered),
                "snap_radius_m": snap_m,
                "filters": {"years": years, "severities": severities, "modes": modes},
            },
        }

    per_street, meta, contributing, unsnapped = aggregate_by_street(
        filtered, streets, center_lonlat=center_lonlat, snap_m=snap_m
    )

    features = []
    max_score = 0
    for idx, agg in per_street.items():
        info = meta[idx]
        if info is None:
            continue
        max_score = max(max_score, agg["severity_score"])
        features.append(
            {
                "type": "Feature",
                "geometry": info["geometry"],
                "properties": {
                    "street_name": info["name"],
                    "accident_count": agg["accident_count"],
                    "severity_score": agg["severity_score"],
                    "fatal": agg["fatal"],
                    "serious": agg["serious"],
                    "minor": agg["minor"],
                    "by_mode": agg["by_mode"],
                    "snap_radius_m": snap_m,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "method": "snapped",
            "max_score": max_score,
            "contributing_accidents": contributing,
            "unsnapped_accidents": unsnapped,
            "snap_radius_m": snap_m,
            "filters": {"years": years, "severities": severities, "modes": modes},
        },
    }


def find_cycling_gaps(
    accidents,
    streets,
    bike_ways,
    *,
    center_lonlat,
    snap_m=DEFAULT_SNAP_M,
    gap_m=DEFAULT_GAP_M,
    min_score=DEFAULT_MIN_SCORE,
):
    """Identify streets with many cyclist accidents and no nearby bike infra.

    Returns a list of dicts (sorted by score desc): one per "gap" street —
    a street whose cyclist-accident score is ≥ ``min_score`` and whose nearest
    bike way is farther than ``gap_m`` metres away. These are the segments
    worth prioritising for protected cycling infrastructure.
    """
    cyclist_accidents = _filter_accidents(
        accidents, years=None, severities=None, modes=["cyclist"]
    )
    if not cyclist_accidents or not streets:
        return []

    per_street, meta, _contrib, _unsnapped = aggregate_by_street(
        cyclist_accidents, streets, center_lonlat=center_lonlat, snap_m=snap_m
    )

    transform = _make_projector(center_lonlat)

    # Project bike-way segments once for the distance check.
    bike_segments = []
    for feat in bike_ways or []:
        for line in _iter_linestrings(feat.get("geometry") or {}):
            pts = [transform(c[0], c[1]) for c in line if len(c) >= 2]
            for a, b in zip(pts, pts[1:]):
                bike_segments.append((a[0], a[1], b[0], b[1]))

    def _nearest_bike_dist(projected_lines):
        if not bike_segments:
            return float("inf")
        best2 = float("inf")
        for pts in projected_lines:
            for px, py in pts:
                for x1, y1, x2, y2 in bike_segments:
                    d2 = _seg_dist2(px, py, x1, y1, x2, y2)
                    if d2 < best2:
                        best2 = d2
        return best2 ** 0.5

    gaps = []
    for idx, agg in per_street.items():
        if agg["severity_score"] < min_score:
            continue
        info = meta[idx]
        if info is None:
            continue
        bike_dist = _nearest_bike_dist(info["projected_lines"])
        if bike_dist <= gap_m:
            continue
        gaps.append(
            {
                "street_index": idx,
                "street_name": info["name"],
                "geometry": info["geometry"],
                "cyclist_accident_count": agg["accident_count"],
                "severity_score": agg["severity_score"],
                "nearest_bike_m": None if bike_dist == float("inf") else round(bike_dist, 1),
            }
        )

    gaps.sort(key=lambda g: g["severity_score"], reverse=True)
    return gaps
