"""Temporal availability / gap analysis for shared mobility.

GBFS feeds are real-time only — a single snapshot says where vehicles are
*right now*, not whether a place is reliably served. To answer the planner's
question — "where can someone usually find a free bike or car, and where are
the persistent gaps?" — we record snapshots over time (see the
``collect_mobility_snapshots`` management command and the
:class:`datasets.models.MobilitySnapshot` model) and aggregate them here.

The aggregation is spatial-grid based so it works for free-floating fleets
(where vehicle IDs rotate and have no fixed home) as well as station feeds:
every observed vehicle is binned into a fixed grid cell, and across all
snapshots in a time window each cell gets:

- ``samples``           — number of snapshots in the window
- ``mean_count``        — average vehicles available in the cell
- ``max_count``         — peak vehicles available
- ``availability_rate`` — fraction of snapshots where the cell had ≥1 vehicle
- ``gap_rate``          — ``1 - availability_rate``; the headline planner
  signal (a cell that is usually empty is a candidate for more vehicles or
  rebalancing)

All functions here are pure and city-agnostic: the grid is derived from a
cell size in metres plus the workspace's centre latitude, never from any
hard-coded place. They are deliberately free of Django imports so they can be
unit-tested without a database.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

# Default analysis grid resolution. ~400 m matches the transit-coverage
# default and is a reasonable "walk to a vehicle" catchment.
DEFAULT_CELL_SIZE_M = 400

# Sentinel form-factor bucket used when a feed does not type its vehicles
# (e.g. a classic station feed reporting only a count).
ANY_FACTOR = "_all"


def grid_steps(center_lat: float, cell_size_m: float) -> tuple[float, float]:
    """Return ``(lon_step, lat_step)`` in degrees for a square-ish metric grid.

    Uses the flat-earth metres-per-degree approximation evaluated at the
    workspace centre latitude, so cells stay a consistent physical size across
    a city. Accurate to well under a percent for a single municipality.
    """
    lat_rad = math.radians(center_lat)
    lat_step = cell_size_m / 110_574
    lon_step = cell_size_m / max(111_320 * math.cos(lat_rad), 1e-6)
    return lon_step, lat_step


def cell_key(lon: float, lat: float, lon_step: float, lat_step: float) -> str:
    """Map a coordinate to its integer grid-cell key ``"i:j"``."""
    i = math.floor(lon / lon_step)
    j = math.floor(lat / lat_step)
    return f"{i}:{j}"


def cell_polygon(key: str, lon_step: float, lat_step: float) -> list[list[float]]:
    """Return the closed polygon ring for a cell key (WGS84)."""
    i_str, j_str = key.split(":")
    i, j = int(i_str), int(j_str)
    x0, y0 = i * lon_step, j * lat_step
    x1, y1 = (i + 1) * lon_step, (j + 1) * lat_step
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def feature_weight_and_factor(feature: dict) -> tuple[float, float, float, str] | None:
    """Extract ``(lon, lat, weight, form_factor)`` from a normalized feature.

    Returns ``None`` for features without a usable point geometry. ``weight``
    is the number of available vehicles the feature represents: 1 for an
    individual free-floating vehicle, or ``num_vehicles_available`` for a
    station feature. ``form_factor`` falls back to :data:`ANY_FACTOR`.
    """
    geom = (feature or {}).get("geometry") or {}
    if geom.get("type") != "Point":
        return None
    coords = geom.get("coordinates") or []
    if len(coords) != 2:
        return None
    lon, lat = coords[0], coords[1]
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return None

    props = feature.get("properties") or {}
    factor = props.get("form_factor") or ANY_FACTOR

    # Station features carry an availability count; individual vehicles count 1.
    if "num_vehicles_available" in props:
        weight = props.get("num_vehicles_available")
        weight = float(weight) if isinstance(weight, (int, float)) else 0.0
    else:
        weight = 1.0
    return lon, lat, weight, factor


def bin_features_to_grid(
    features: list[dict], lon_step: float, lat_step: float
) -> dict[str, dict[str, float]]:
    """Aggregate one snapshot's features into ``{cell_key: {form_factor: count}}``."""
    grid: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for feature in features or []:
        parsed = feature_weight_and_factor(feature)
        if parsed is None:
            continue
        lon, lat, weight, factor = parsed
        if weight <= 0:
            continue
        key = cell_key(lon, lat, lon_step, lat_step)
        grid[key][factor] += weight
    # Convert to plain dicts so the result is JSON-serializable for storage.
    return {k: dict(v) for k, v in grid.items()}


def _selected_sum(cell: dict[str, float], form_factors: list[str] | None) -> float:
    if form_factors is None:
        return sum(cell.values())
    return sum(cell.get(f, 0.0) for f in form_factors)


def compute_gap_grid(
    snapshot_grids: list[dict[str, dict[str, float]]],
    lon_step: float,
    lat_step: float,
    *,
    form_factors: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate per-snapshot grids into a gap-analysis FeatureCollection.

    ``snapshot_grids`` is the list of ``cell_counts`` dicts (one per snapshot
    already filtered to the desired time window). Each output feature is the
    polygon of a cell that held at least one vehicle in at least one snapshot,
    carrying the availability/gap statistics described in the module docstring.

    Returns a GeoJSON ``FeatureCollection`` with an extra top-level
    ``samples`` member (the number of snapshots aggregated).
    """
    samples = len(snapshot_grids)
    if samples == 0:
        return {"type": "FeatureCollection", "features": [], "samples": 0}

    present: dict[str, int] = defaultdict(int)
    total: dict[str, float] = defaultdict(float)
    peak: dict[str, float] = defaultdict(float)

    for grid in snapshot_grids:
        for key, cell in grid.items():
            value = _selected_sum(cell, form_factors)
            if value <= 0:
                continue
            present[key] += 1
            total[key] += value
            if value > peak[key]:
                peak[key] = value

    features = []
    for key in sorted(present.keys()):
        present_samples = present[key]
        availability_rate = present_samples / samples
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [cell_polygon(key, lon_step, lat_step)],
                },
                "properties": {
                    "cell": key,
                    "samples": samples,
                    "present_samples": present_samples,
                    "mean_count": round(total[key] / samples, 2),
                    "max_count": round(peak[key], 2),
                    "availability_rate": round(availability_rate, 3),
                    "gap_rate": round(1 - availability_rate, 3),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features, "samples": samples}
