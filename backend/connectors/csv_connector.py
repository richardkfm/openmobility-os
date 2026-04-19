"""CSV connector — reads delimited files with coordinates or WKT geometry.

Fully implemented. Supports URL fetch, configurable delimiter/encoding,
auto-detection of common coordinate column names, and WKT geometry column.
"""

import csv
import io

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult

LAT_CANDIDATES = ("lat", "latitude", "y", "y_coord", "ycoord", "breitengrad")
LON_CANDIDATES = ("lon", "lng", "long", "longitude", "x", "x_coord", "xcoord", "laengengrad")


class CSVConnector(BaseConnector):
    id = "csv"
    display_name_de = "CSV-Datei (URL)"
    display_name_en = "CSV file (URL)"
    description_de = (
        "Lädt eine CSV-Datei per URL. Erkennt Koordinaten-Spalten automatisch "
        "(lat/lon, latitude/longitude etc.) oder liest WKT-Geometrie."
    )
    description_en = (
        "Fetches a CSV from a URL. Auto-detects coordinate columns "
        "(lat/lon, latitude/longitude, etc.) or reads WKT geometry."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "CSV URL"},
        "delimiter": {"type": "string", "default": ",", "label": "Delimiter"},
        "encoding": {"type": "string", "default": "utf-8", "label": "Encoding"},
        "lat_col": {"type": "string", "label": "Latitude column (optional)"},
        "lon_col": {"type": "string", "label": "Longitude column (optional)"},
        "wkt_col": {"type": "string", "label": "WKT geometry column (optional)"},
        "skip_rows": {"type": "integer", "default": 0, "label": "Header skip rows"},
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("CSV URL is required.")
        return errors

    def _read_rows(self, config):
        url = config["url"]
        encoding = config.get("encoding", "utf-8")
        delimiter = config.get("delimiter", ",")
        skip = int(config.get("skip_rows", 0) or 0)

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        text = response.content.decode(encoding, errors="replace")

        lines = text.splitlines()
        if skip:
            lines = lines[skip:]
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        return list(reader), reader.fieldnames or []

    def _resolve_cols(self, config, fieldnames):
        lat = config.get("lat_col") or self._autodetect(fieldnames, LAT_CANDIDATES)
        lon = config.get("lon_col") or self._autodetect(fieldnames, LON_CANDIDATES)
        return lat, lon

    @staticmethod
    def _autodetect(fieldnames, candidates):
        lowered = {f.lower().strip(): f for f in fieldnames}
        for cand in candidates:
            if cand in lowered:
                return lowered[cand]
        return None

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            rows, fieldnames = self._read_rows(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")

        lat_col, lon_col = self._resolve_cols(config, fieldnames)
        wkt_col = config.get("wkt_col")
        if not (lat_col and lon_col) and not wkt_col:
            return ConnectorTestResult(
                False,
                f"No coordinate columns detected. Available columns: {fieldnames}",
            )
        preview = [self._row_to_feature(r, lat_col, lon_col, wkt_col) for r in rows[:3]]
        return ConnectorTestResult(
            True,
            f"CSV OK. Found {len(rows)} rows. Columns used: lat={lat_col}, lon={lon_col}, wkt={wkt_col}.",
            [f for f in preview if f],
        )

    def fetch(self, config, workspace=None):
        rows, fieldnames = self._read_rows(config)
        lat_col, lon_col = self._resolve_cols(config, fieldnames)
        wkt_col = config.get("wkt_col")

        features = []
        for row in rows:
            feat = self._row_to_feature(row, lat_col, lon_col, wkt_col)
            if feat:
                features.append(feat)

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )

    def _row_to_feature(self, row, lat_col, lon_col, wkt_col):
        geometry = None
        if wkt_col and row.get(wkt_col):
            geometry = _wkt_to_geojson(row[wkt_col])
        elif lat_col and lon_col:
            lat = _safe_float(row.get(lat_col))
            lon = _safe_float(row.get(lon_col))
            if lat is None or lon is None:
                return None
            geometry = {"type": "Point", "coordinates": [lon, lat]}

        if geometry is None:
            return None

        properties = {k: v for k, v in row.items() if k not in {lat_col, lon_col, wkt_col}}
        return {"type": "Feature", "geometry": geometry, "properties": properties}


def _safe_float(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _wkt_to_geojson(wkt: str):
    """Very small WKT → GeoJSON converter for POINT, LINESTRING, POLYGON."""
    wkt = wkt.strip().upper()
    if wkt.startswith("POINT"):
        coords = _parse_coord_list(_between(wkt, "(", ")"))
        return {"type": "Point", "coordinates": coords[0]}
    if wkt.startswith("LINESTRING"):
        coords = _parse_coord_list(_between(wkt, "(", ")"))
        return {"type": "LineString", "coordinates": coords}
    if wkt.startswith("POLYGON"):
        inner = _between(wkt, "((", "))")
        coords = _parse_coord_list(inner)
        return {"type": "Polygon", "coordinates": [coords]}
    return None


def _between(text: str, start: str, end: str) -> str:
    s = text.find(start)
    e = text.rfind(end)
    if s == -1 or e == -1:
        return ""
    return text[s + len(start) : e]


def _parse_coord_list(s: str):
    result = []
    for part in s.split(","):
        tokens = part.strip().split()
        if len(tokens) >= 2:
            try:
                result.append([float(tokens[0]), float(tokens[1])])
            except ValueError:
                continue
    return result
