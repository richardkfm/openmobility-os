"""Destatis Zensus 2022 100m population grid connector.

Reads the CSV grid-cell export from https://www.zensus2022.de and converts
INSPIRE grid cell IDs (EPSG:3035) into WGS84 polygons. Each 100m × 100m
cell becomes a GeoJSON Feature carrying its population and demographic
indicator values as properties.

The connector is workspace-bbox-aware: when a workspace with bounds is
supplied, only cells overlapping the workspace's bounding box are emitted.
For Leipzig (~300 km²) this typically yields ~30 000 cells — manageable
for PostGIS storage and MapLibre rendering at medium zoom levels.

Config fields:
- ``url`` — URL to the Zensus 2022 CSV (semicolon-delimited by default)
- ``grid_id_column`` — column containing the INSPIRE grid cell ID
  (default ``Gitter_ID_100m``)
- ``indicator_columns`` — list of column names to include as feature
  properties (e.g. ``["Einwohner", "Alter_unter_18", "Alter_65_und_aelter"]``)
- ``min_population`` — only emit cells where the primary population column
  exceeds this threshold (default 1, skips empty cells)
- ``population_column`` — which indicator column represents total population
  (default: first entry of ``indicator_columns``)
- ``delimiter`` / ``encoding`` — CSV parsing options

License: Zensus 2022 data is published under DL-DE BY 2.0.
"""

from __future__ import annotations

import csv
import io
import re

import pyproj
import requests

from ._http import request_kwargs
from .base import BaseConnector, ConnectorTestResult, FetchResult

_GRID_PATTERN = re.compile(
    r"(\d+)m[Nn](\d+)[Ee](\d+)"
)

_TRANSFORMER = None


def _get_transformer():
    global _TRANSFORMER
    if _TRANSFORMER is None:
        _TRANSFORMER = pyproj.Transformer.from_crs(
            "EPSG:3035", "EPSG:4326", always_xy=True
        )
    return _TRANSFORMER


def _parse_grid_id(grid_id: str):
    """Parse an INSPIRE grid cell ID into (resolution_m, easting_m, northing_m).

    Example: '100mN26850E43350' → (100, 4335000, 2685000)
    """
    m = _GRID_PATTERN.search(grid_id)
    if not m:
        return None
    res = int(m.group(1))
    northing = int(m.group(2)) * res
    easting = int(m.group(3)) * res
    return res, easting, northing


def _cell_to_polygon_wgs84(easting: int, northing: int, resolution: int):
    """Convert a grid cell's SW corner + resolution to a WGS84 polygon."""
    t = _get_transformer()
    sw = t.transform(easting, northing)
    se = t.transform(easting + resolution, northing)
    ne = t.transform(easting + resolution, northing + resolution)
    nw = t.transform(easting, northing + resolution)
    return {
        "type": "Polygon",
        "coordinates": [[
            [round(sw[0], 7), round(sw[1], 7)],
            [round(se[0], 7), round(se[1], 7)],
            [round(ne[0], 7), round(ne[1], 7)],
            [round(nw[0], 7), round(nw[1], 7)],
            [round(sw[0], 7), round(sw[1], 7)],
        ]],
    }


def _in_bbox(lon: float, lat: float, bbox) -> bool:
    """Check if a point falls within (west, south, east, north) bbox."""
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


class ZensusGridConnector(BaseConnector):
    id = "zensus_grid"
    display_name_de = "Zensus 2022 — Bevölkerungsraster (100 m)"
    display_name_en = "Zensus 2022 — population grid (100 m)"
    description_de = (
        "Liest das Zensus-2022-Gitterzellen-CSV (Destatis, DL-DE BY 2.0) "
        "und konvertiert INSPIRE-Gitter-IDs (EPSG:3035) in WGS84-Polygone. "
        "Jede 100-m-Zelle wird ein GeoJSON-Feature mit den gewählten "
        "Demografie-Indikatoren als Properties."
    )
    description_en = (
        "Reads the Zensus 2022 grid-cell CSV (Destatis, DL-DE BY 2.0) and "
        "converts INSPIRE grid IDs (EPSG:3035) to WGS84 polygons. Each 100 m "
        "cell becomes a GeoJSON Feature carrying the selected demographic "
        "indicators as properties."
    )

    config_schema = {
        "url": {
            "type": "string",
            "required": True,
            "label": "CSV download URL",
        },
        "grid_id_column": {
            "type": "string",
            "default": "Gitter_ID_100m",
            "label": "Column containing the INSPIRE grid cell ID",
        },
        "indicator_columns": {
            "type": "array",
            "required": True,
            "label": "Columns to include (e.g. ['Einwohner', 'Alter_unter_18'])",
        },
        "population_column": {
            "type": "string",
            "label": "Which column is total population (default: first indicator)",
        },
        "min_population": {
            "type": "integer",
            "default": 1,
            "label": "Skip cells below this population count",
        },
        "delimiter": {"type": "string", "default": ";", "label": "CSV delimiter"},
        "encoding": {"type": "string", "default": "utf-8", "label": "File encoding"},
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("url is required.")
        if not config.get("indicator_columns"):
            errors.append("indicator_columns is required (list of column names).")
        return errors

    def _read_csv(self, config):
        url = config["url"]
        encoding = config.get("encoding") or "utf-8"
        delimiter = config.get("delimiter") or ";"
        response = requests.get(url, timeout=180, **request_kwargs(config))
        response.raise_for_status()
        text = response.content.decode(encoding, errors="replace")
        reader = csv.DictReader(
            io.StringIO(text), delimiter=delimiter
        )
        return list(reader), reader.fieldnames or []

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            rows, fieldnames = self._read_csv(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")
        grid_col = config.get("grid_id_column") or "Gitter_ID_100m"
        if grid_col not in fieldnames:
            return ConnectorTestResult(
                False,
                f"Grid ID column '{grid_col}' not found. "
                f"Available: {fieldnames[:20]}",
            )
        indicators = config.get("indicator_columns") or []
        missing = [c for c in indicators if c not in fieldnames]
        if missing:
            return ConnectorTestResult(
                False,
                f"Indicator columns not found: {missing}. "
                f"Available: {fieldnames[:20]}",
            )
        return ConnectorTestResult(
            True,
            f"Zensus CSV OK. {len(rows)} rows, columns include {grid_col}.",
            [],
        )

    def fetch(self, config, workspace=None):
        rows, _ = self._read_csv(config)
        grid_col = config.get("grid_id_column") or "Gitter_ID_100m"
        indicators = config.get("indicator_columns") or []
        pop_col = config.get("population_column") or (indicators[0] if indicators else None)
        min_pop = int(config.get("min_population") or 1)

        bbox = None
        if workspace and getattr(workspace, "bounds", None):
            bbox = workspace.bounds.extent

        features = []
        for row in rows:
            parsed = _parse_grid_id(row.get(grid_col, ""))
            if not parsed:
                continue
            resolution, easting, northing = parsed

            if pop_col:
                pop_val = _safe_int(row.get(pop_col))
                if pop_val is not None and pop_val < min_pop:
                    continue

            polygon = _cell_to_polygon_wgs84(easting, northing, resolution)

            if bbox:
                centroid_lon = polygon["coordinates"][0][0][0]
                centroid_lat = polygon["coordinates"][0][0][1]
                if not _in_bbox(centroid_lon, centroid_lat, bbox):
                    continue

            props = {}
            for col in indicators:
                val = _safe_int(row.get(col))
                props[col] = val if val is not None else row.get(col)

            features.append({
                "type": "Feature",
                "geometry": polygon,
                "properties": props,
            })

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _safe_int(value):
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(str(value).replace(".", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None
