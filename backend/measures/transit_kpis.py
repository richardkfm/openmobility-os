"""Transit KPIs derived from the ``transit_stops`` feature set.

Numbers surfaced on the workspace dashboard and public API. All math runs in
plain Python so tests and small self-hosters do not need PostGIS to compute
coverage statistics.

Returned keys (all optional — missing when the data is insufficient):

``stop_count``
    Number of normalized stops on record.

``avg_headway_min``
    Arithmetic mean of per-stop ``avg_headway_min`` values. ``None`` when no
    stop carries headway info.

``night_service_pct``
    Share (0–100) of stops with ``night_service == True``.

``barrier_free_pct``
    Among stops whose ``wheelchair_boarding`` is known (``yes``/``no``), the
    share flagged ``yes``.

``coverage_pct``
    Share (0–100) of the workspace bounding box covered by the union of stop
    buffer polygons, when a ``transit_coverage`` feature set is available.

``population_in_coverage``
    ``coverage_pct`` × workspace.population, rounded to an integer. Only
    returned when both values are available.
"""

from __future__ import annotations

from typing import Any


def compute_transit_kpis(workspace, feature_sets) -> dict[str, Any]:
    stops_fs = _select(feature_sets, "transit_stops")
    coverage_fs = _select(feature_sets, "transit_coverage")
    if not stops_fs and not coverage_fs:
        return {}

    kpis: dict[str, Any] = {}

    if stops_fs:
        stops = stops_fs.feature_collection.get("features", [])
        kpis["stop_count"] = len(stops)

        headways = [
            (f.get("properties") or {}).get("avg_headway_min")
            for f in stops
        ]
        headways = [h for h in headways if isinstance(h, (int, float))]
        if headways:
            kpis["avg_headway_min"] = round(sum(headways) / len(headways), 1)

        if stops:
            night_count = sum(
                1 for f in stops
                if (f.get("properties") or {}).get("night_service") is True
            )
            kpis["night_service_pct"] = round(100 * night_count / len(stops), 1)

        rated = [
            f for f in stops
            if (f.get("properties") or {}).get("wheelchair_boarding") in ("yes", "no")
        ]
        if rated:
            yes_count = sum(
                1 for f in rated
                if (f["properties"] or {}).get("wheelchair_boarding") == "yes"
            )
            kpis["barrier_free_pct"] = round(100 * yes_count / len(rated), 1)

    if coverage_fs and workspace.bounds:
        coverage_polys = [
            f.get("geometry") for f in coverage_fs.feature_collection.get("features", [])
        ]
        coverage_pct = _coverage_percentage(coverage_polys, workspace.bounds.extent)
        if coverage_pct is not None:
            rounded = round(coverage_pct, 1)
            kpis["coverage_pct"] = rounded
            if workspace.population:
                kpis["population_in_coverage"] = int(
                    workspace.population * rounded / 100
                )

    return kpis


def _select(feature_sets, layer_kind: str):
    for fs in feature_sets:
        if fs.layer_kind == layer_kind:
            return fs
    return None


def _coverage_percentage(
    polygons: list[dict | None],
    bounds_extent: tuple[float, float, float, float],
) -> float | None:
    """Estimate the % of ``bounds_extent`` covered by the polygon union.

    Uses a light-weight raster rasterization — good enough for headline KPIs,
    avoids pulling in Shapely for what is ultimately a visualization number.
    Returns ``None`` when we cannot compute a meaningful answer.
    """
    west, south, east, north = bounds_extent
    if east <= west or north <= south:
        return None

    ellipses: list[tuple[float, float, float, float]] = []
    for geom in polygons:
        if not geom or geom.get("type") != "Polygon":
            continue
        ring = (geom.get("coordinates") or [[]])[0]
        if len(ring) < 4:
            continue
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        lon_c = (min(lons) + max(lons)) / 2
        lat_c = (min(lats) + max(lats)) / 2
        r_lon = (max(lons) - min(lons)) / 2
        r_lat = (max(lats) - min(lats)) / 2
        if r_lon <= 0 or r_lat <= 0:
            continue
        ellipses.append((lon_c, lat_c, r_lon, r_lat))

    if not ellipses:
        return None

    grid_n = 64
    step_x = (east - west) / grid_n
    step_y = (north - south) / grid_n
    covered = 0
    total = 0
    for i in range(grid_n):
        lon = west + step_x * (i + 0.5)
        for j in range(grid_n):
            lat = south + step_y * (j + 0.5)
            total += 1
            for lon_c, lat_c, r_lon, r_lat in ellipses:
                dx = (lon - lon_c) / r_lon
                dy = (lat - lat_c) / r_lat
                if dx * dx + dy * dy <= 1.0:
                    covered += 1
                    break
    return 100 * covered / total if total else None
