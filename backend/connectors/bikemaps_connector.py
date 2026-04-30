"""BikeMaps.org connector — global crowdsourced cycling incident data.

BikeMaps.org (https://bikemaps.org) is a citizen-science platform run by the
University of Victoria where cyclists report collisions, near misses, hazards,
and thefts. It addresses a known blind spot in police accident statistics:
cyclist incidents — especially near misses — are under-reported by an order of
magnitude in official crash records, yet they are exactly the early-warning
signals municipal safety teams need.

This connector pulls reports for an arbitrary bounding box (typically the
workspace bounds) and normalizes them to the OpenMobility OS standard accident
property schema. Reports are tagged with `incident_type` so the UI can clearly
distinguish crowdsourced near-miss / hazard data from authoritative police
records (e.g. Destatis Unfallatlas).

License: BikeMaps.org incident data is published under CC BY 4.0
(https://bikemaps.org/about). Always preserve the attribution string.
"""

from __future__ import annotations

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult

DEFAULT_API_URL = "https://bikemaps.org/incidents.json"

# BikeMaps incident_type → kept by default?
# Collisions and near misses are safety-relevant; hazards and thefts are
# not in scope for the accident layer but can be opted in via config.
_INCIDENT_TYPES = {
    "collision": {"category": "collision", "default": True},
    "nearmiss": {"category": "near_miss", "default": True},
    "near miss": {"category": "near_miss", "default": True},
    "near_miss": {"category": "near_miss", "default": True},
    "hazard": {"category": "hazard", "default": False},
    "theft": {"category": "theft", "default": False},
}

# BikeMaps `injury` free-text → normalized severity.
# We match by lowercased substring so minor BikeMaps wording changes do not
# silently drop data.
_INJURY_SEVERITY = [
    ("fatal", "fatal"),
    ("overnight", "serious"),
    ("hospital", "serious"),
    ("treatment required", "minor"),
    ("no treatment", "minor"),
    ("no injury", "minor"),
]

# BikeMaps `incident_with` → additional involved modes (cyclist is implicit).
_WITH_MODES = [
    ("vehicle", "car"),
    ("car", "car"),
    ("truck", "truck"),
    ("bus", "bus"),
    ("door", "car"),
    ("pedestrian", "pedestrian"),
    ("scooter", "scooter"),
]


class BikeMapsConnector(BaseConnector):
    id = "bikemaps"
    display_name_de = "BikeMaps.org (Crowdsourced Rad-Meldungen)"
    display_name_en = "BikeMaps.org (crowdsourced cycling reports)"
    description_de = (
        "Lädt Kollisionen und Beinahe-Unfälle von BikeMaps.org — einer "
        "globalen Bürgerwissenschafts-Plattform für Rad-Vorfälle. Schließt "
        "die bekannte Untererfassung verletzlicher Verkehrsteilnehmender in "
        "polizeilichen Statistiken. Lizenz: CC BY 4.0."
    )
    description_en = (
        "Fetches collisions and near-misses from BikeMaps.org — a global "
        "citizen-science platform for cycling incidents. Closes the known "
        "under-reporting gap for vulnerable road users in police records. "
        "License: CC BY 4.0."
    )

    config_schema = {
        "url": {
            "type": "string",
            "default": DEFAULT_API_URL,
            "label": "BikeMaps API URL (default: bikemaps.org/incidents.json)",
        },
        "bbox": {
            "type": "string",
            "label": (
                "Bounding box 'west,south,east,north' (WGS84). If omitted "
                "and a workspace is supplied, the workspace bounds are used."
            ),
        },
        "include_collisions": {"type": "boolean", "default": True, "label": "Include collisions"},
        "include_near_misses": {
            "type": "boolean",
            "default": True,
            "label": "Include near misses (recommended — closes police-data gap)",
        },
        "include_hazards": {
            "type": "boolean",
            "default": False,
            "label": "Include hazard reports",
        },
        "start_year": {"type": "integer", "label": "Earliest year (optional)"},
        "end_year": {"type": "integer", "label": "Latest year (optional)"},
        "max_records": {
            "type": "integer",
            "default": 5000,
            "label": "Hard cap on records imported (safety against runaway pagination)",
        },
    }

    def validate_config(self, config):
        errors = []
        bbox = _parse_bbox(config.get("bbox"))
        if config.get("bbox") and bbox is None:
            errors.append("bbox must be 'west,south,east,north' in decimal degrees.")
        for key in ("start_year", "end_year"):
            v = config.get(key)
            if v in (None, ""):
                continue
            try:
                year = int(v)
            except (TypeError, ValueError):
                errors.append(f"{key} must be an integer year.")
                continue
            if not 1990 <= year <= 2100:
                errors.append(f"{key} must be between 1990 and 2100.")
        return errors

    def _resolve_bbox(self, config, workspace):
        bbox = _parse_bbox(config.get("bbox"))
        if bbox is not None:
            return bbox
        if workspace is None:
            return None
        bounds = getattr(workspace, "bounds", None)
        if bounds is None:
            return None
        try:
            return tuple(bounds.extent)
        except (AttributeError, TypeError):
            return None

    def _fetch_raw(self, config, bbox):
        url = config.get("url") or DEFAULT_API_URL
        params: dict[str, str] = {}
        if bbox is not None:
            west, south, east, north = bbox
            params["bbox"] = f"{west},{south},{east},{north}"

        max_records = int(config.get("max_records") or 5000)
        collected: list[dict] = []
        next_url: str | None = url
        next_params: dict | None = params
        # BikeMaps DRF responses may either return a GeoJSON FeatureCollection
        # or a paginated `{count, next, results}` envelope. Handle both.
        while next_url and len(collected) < max_records:
            response = requests.get(next_url, params=next_params, timeout=120)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
                collected.extend(payload.get("features") or [])
                # GeoJSON endpoint is non-paginated.
                break
            if isinstance(payload, dict) and "results" in payload:
                collected.extend(payload.get("results") or [])
                next_url = payload.get("next")
                next_params = None  # `next` already encodes params
                continue
            if isinstance(payload, list):
                collected.extend(payload)
                break
            break
        return collected[:max_records]

    def _filters(self, config):
        return {
            "collision": bool(config.get("include_collisions", True)),
            "near_miss": bool(config.get("include_near_misses", True)),
            "hazard": bool(config.get("include_hazards", False)),
            "theft": False,
            "start_year": _safe_int(config.get("start_year")),
            "end_year": _safe_int(config.get("end_year")),
        }

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        bbox = self._resolve_bbox(config, workspace)
        if bbox is None:
            return ConnectorTestResult(
                False,
                "BikeMaps requires either an explicit bbox or a workspace with bounds set.",
            )
        try:
            raw = self._fetch_raw(config, bbox)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")

        filters = self._filters(config)
        features = [f for r in raw if (f := _record_to_feature(r, filters)) is not None]
        return ConnectorTestResult(
            True,
            f"BikeMaps OK. {len(raw)} raw reports, {len(features)} kept after filtering.",
            features[:3],
        )

    def fetch(self, config, workspace=None):
        bbox = self._resolve_bbox(config, workspace)
        if bbox is None:
            raise ValueError(
                "BikeMaps fetch requires a bbox (or workspace.bounds). "
                "Set the workspace bounding box or configure 'bbox'."
            )
        raw = self._fetch_raw(config, bbox)
        filters = self._filters(config)
        features = [f for r in raw if (f := _record_to_feature(r, filters)) is not None]
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _record_to_feature(record, filters):
    """Normalize one BikeMaps record (GeoJSON Feature OR plain dict) to the
    OpenMobility OS accident schema."""
    if not isinstance(record, dict):
        return None

    # Two shapes: GeoJSON Feature {geometry, properties} OR flat dict with
    # `geom`/`point`/`latitude`+`longitude`/`p_x`+`p_y`.
    geometry = record.get("geometry")
    props = record.get("properties") if "properties" in record else record

    lon, lat = _extract_lonlat(geometry, props)
    if lon is None or lat is None:
        return None

    incident_raw = str(props.get("incident_type") or props.get("p_type") or "").strip().lower()
    incident_meta = _INCIDENT_TYPES.get(incident_raw) or _match_incident_type(incident_raw)
    if incident_meta is None:
        return None
    category = incident_meta["category"]
    if not filters.get(category, False):
        return None

    severity = _severity_from_injury(props.get("injury") or props.get("p_injury") or "")
    if category == "near_miss":
        severity = "minor"  # near miss → no actual injury

    incident_with = str(props.get("incident_with") or props.get("p_incident_with") or "").lower()
    involved_modes = ["cyclist"]
    for needle, mode in _WITH_MODES:
        if needle in incident_with and mode not in involved_modes:
            involved_modes.append(mode)

    date_raw = props.get("incident_date") or props.get("date") or props.get("p_date") or ""
    date_str = str(date_raw).strip() or None
    year = _extract_year(date_str)
    if year is not None:
        if filters.get("start_year") and year < filters["start_year"]:
            return None
        if filters.get("end_year") and year > filters["end_year"]:
            return None

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "severity": severity,
            "date": date_str,
            "year": year,
            "time_of_day": None,
            "weather": None,
            "involved_modes": involved_modes,
            "vulnerable_road_user": True,
            "speed_limit": None,
            "intersection_type": None,
            # Crowdsourcing-specific extras — these let the UI / scoring
            # layer down-weight non-collision reports and disclose source.
            "incident_type": category,
            "data_origin": "crowdsourced",
            "source_platform": "bikemaps.org",
        },
    }


def _extract_lonlat(geometry, props):
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coords = geometry.get("coordinates") or []
        if len(coords) >= 2:
            return _safe_float(coords[0]), _safe_float(coords[1])
    if isinstance(props, dict):
        for lon_key, lat_key in (("longitude", "latitude"), ("p_x", "p_y"), ("lon", "lat")):
            if lon_key in props and lat_key in props:
                return _safe_float(props.get(lon_key)), _safe_float(props.get(lat_key))
    return None, None


def _match_incident_type(raw):
    if not raw:
        return None
    for key, meta in _INCIDENT_TYPES.items():
        if key in raw:
            return meta
    return None


def _severity_from_injury(raw):
    text = str(raw).lower()
    for needle, severity in _INJURY_SEVERITY:
        if needle in text:
            return severity
    return "minor"


def _extract_year(date_str):
    if not date_str:
        return None
    for token in (date_str[:4], date_str[-4:]):
        if token.isdigit() and 1990 <= int(token) <= 2100:
            return int(token)
    return None


def _safe_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
