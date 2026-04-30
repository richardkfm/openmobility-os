"""Unfallatlas connector — German Federal Statistics Office accident data.

Reads the Destatis Unfallatlas CSV format (semicolon-delimited) and normalizes
it to the OpenMobility OS standard accident property schema.

Data source: https://unfallatlas.statistikportal.de/ (Destatis)
License: dl-de/by-2-0 (Datenlizenz Deutschland – Namensnennung)
"""

import csv
import io

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult

SEVERITY_MAP = {"1": "fatal", "2": "serious", "3": "minor"}

MODE_FLAGS = [
    ("IstRad", "cyclist"),
    ("IstPKW", "car"),
    ("IstFuss", "pedestrian"),
    ("IstKrad", "motorbike"),
    ("IstGkfz", "truck"),
    ("IstSonstige", "other"),
]

REQUIRED_COLUMNS = {"XGCSWGS84", "YGCSWGS84", "UKATEGORIE"}


class UnfallatlasConnector(BaseConnector):
    id = "unfallat"
    display_name_de = "Unfallatlas (Destatis, Deutschland)"
    display_name_en = "Unfallatlas (Destatis, Germany)"
    description_de = (
        "Liest Unfalldaten aus dem deutschen Unfallatlas (Statistisches Bundesamt). "
        "Erwartet eine CSV-Datei im Destatis-Format mit XGCSWGS84/YGCSWGS84-Koordinaten "
        "und UKATEGORIE-Schweregradschlüssel."
    )
    description_en = (
        "Reads accident data from the German Unfallatlas (Federal Statistical Office). "
        "Expects a CSV file in Destatis format with XGCSWGS84/YGCSWGS84 coordinates "
        "and UKATEGORIE severity key."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "CSV download URL"},
        "encoding": {
            "type": "string",
            "default": "utf-8",
            "label": "File encoding (utf-8 or latin-1)",
        },
        "bbox": {
            "type": "string",
            "label": (
                "Optional bounding box 'west,south,east,north' (WGS84). "
                "Rows outside the box are dropped. If omitted and a workspace "
                "is supplied during sync, the workspace bounds are used."
            ),
        },
        "clip_to_workspace": {
            "type": "boolean",
            "default": True,
            "label": "When no explicit bbox is set, clip to workspace bounds.",
        },
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("CSV URL is required.")
        bbox = _parse_bbox(config.get("bbox"))
        if config.get("bbox") and bbox is None:
            errors.append("bbox must be 'west,south,east,north' in decimal degrees.")
        return errors

    def _fetch_rows(self, config):
        url = config["url"]
        encoding = config.get("encoding", "utf-8")
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        text = response.content.decode(encoding, errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        rows = list(reader)
        fieldnames = reader.fieldnames or []
        return rows, fieldnames

    def _resolve_bbox(self, config, workspace):
        bbox = _parse_bbox(config.get("bbox"))
        if bbox is not None:
            return bbox
        clip = config.get("clip_to_workspace", True)
        if not clip or workspace is None:
            return None
        bounds = getattr(workspace, "bounds", None)
        if bounds is None:
            return None
        # GeoDjango Polygon.extent → (west, south, east, north).
        try:
            return tuple(bounds.extent)
        except (AttributeError, TypeError):
            return None

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            rows, fieldnames = self._fetch_rows(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")
        present = {f.strip() for f in fieldnames}
        missing = REQUIRED_COLUMNS - present
        if missing:
            return ConnectorTestResult(
                False,
                f"Missing required columns: {sorted(missing)}. Found: {fieldnames[:12]}",
            )
        bbox = self._resolve_bbox(config, workspace)
        preview = [_row_to_feature(r, bbox) for r in rows[:50]]
        kept = [f for f in preview if f]
        suffix = f" (bbox-clip active, sample {len(kept)}/{len(preview)} kept)" if bbox else ""
        return ConnectorTestResult(
            True,
            f"Unfallatlas CSV OK. {len(rows)} rows, required columns detected{suffix}.",
            kept[:3],
        )

    def fetch(self, config, workspace=None):
        rows, _ = self._fetch_rows(config)
        bbox = self._resolve_bbox(config, workspace)
        features = [f for r in rows if (f := _row_to_feature(r, bbox)) is not None]
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _row_to_feature(row, bbox=None):
    lon = _safe_float_de(row.get("XGCSWGS84") or row.get("xgcswgs84"))
    lat = _safe_float_de(row.get("YGCSWGS84") or row.get("ygcswgs84"))
    if lon is None or lat is None:
        return None
    if bbox is not None:
        west, south, east, north = bbox
        if not (west <= lon <= east and south <= lat <= north):
            return None

    severity_code = str(row.get("UKATEGORIE", "")).strip()
    severity = SEVERITY_MAP.get(severity_code, "minor")

    involved_modes = [
        mode for col, mode in MODE_FLAGS if str(row.get(col, "0")).strip() == "1"
    ]
    vru = any(m in involved_modes for m in ("cyclist", "pedestrian"))

    year_str = str(row.get("UJAHR", "")).strip()
    month = str(row.get("UMONAT", "")).strip().zfill(2)
    date = f"{year_str}-{month}" if year_str and month else None
    year_int: int | None
    try:
        year_int = int(year_str) if year_str else None
    except ValueError:
        year_int = None

    hour_str = str(row.get("USTUNDE", "")).strip()
    time_of_day = _time_of_day(hour_str)

    weather_code = str(row.get("USTRZUSTAND", "")).strip()
    weather = {"0": "dry", "1": "wet", "2": "snow"}.get(weather_code, "unknown")

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "severity": severity,
            "date": date,
            "year": year_int,
            "time_of_day": time_of_day,
            "weather": weather,
            "involved_modes": involved_modes,
            "vulnerable_road_user": vru,
            "speed_limit": None,
            "intersection_type": _intersection_type(row),
        },
    }


def _parse_bbox(raw):
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            west, south, east, north = (float(v) for v in raw)
        except (TypeError, ValueError):
            return None
    else:
        text = str(raw).strip()
        if not text:
            return None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 4:
            return None
        try:
            west, south, east, north = (float(p) for p in parts)
        except ValueError:
            return None
    if west > east or south > north:
        return None
    return (west, south, east, north)


def _safe_float_de(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def _time_of_day(hour_str):
    try:
        h = int(hour_str)
    except (ValueError, TypeError):
        return "unknown"
    if 6 <= h < 10:
        return "morning"
    if 10 <= h < 17:
        return "day"
    if 17 <= h < 21:
        return "evening"
    return "night"


def _intersection_type(row):
    utyp = str(row.get("UTYP1", "")).strip()
    return {"1": "t_junction", "2": "crossing", "3": "roundabout"}.get(utyp, "none")
