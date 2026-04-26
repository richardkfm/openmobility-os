"""Generic accident CSV connector — international accident data.

Accepts any CSV with user-configured column mapping and normalizes it to the
OpenMobility OS standard accident property schema. Useful for municipalities
outside Germany that publish accident data in their own format.
"""

import csv
import io
import json

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult

DEFAULT_SEVERITY_MAP = {
    "1": "fatal",
    "fatal": "fatal",
    "tödlich": "fatal",
    "2": "serious",
    "serious": "serious",
    "schwer": "serious",
    "3": "minor",
    "minor": "minor",
    "leicht": "minor",
    "slight": "minor",
}

_MODE_ALIASES: dict[str, list[str]] = {
    "cyclist": ["cyclist", "bicycle", "bike", "rad", "fahrrad"],
    "pedestrian": ["pedestrian", "foot", "fuss", "fußgänger"],
    "car": ["car", "pkw", "auto"],
    "motorbike": ["motorbike", "motorcycle", "krad"],
    "truck": ["truck", "hgv", "lkw", "gkfz"],
    "bus": ["bus"],
    "tram": ["tram", "strassenbahn"],
    "scooter": ["scooter", "roller"],
}


class AccidentCSVConnector(BaseConnector):
    id = "accident_csv"
    display_name_de = "Unfalldaten CSV (international)"
    display_name_en = "Accident data CSV (international)"
    description_de = (
        "Universeller Importer für Unfalldaten aus CSV-Dateien mit frei "
        "konfigurierbarem Spalten-Mapping. Gibt das Standard-Unfall-Schema aus "
        "(severity, involved_modes, vulnerable_road_user, …)."
    )
    description_en = (
        "Universal importer for accident data from CSV files with freely "
        "configurable column mapping. Outputs the standard accident schema "
        "(severity, involved_modes, vulnerable_road_user, …)."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "CSV URL"},
        "lat_col": {"type": "string", "required": True, "label": "Latitude column name"},
        "lon_col": {"type": "string", "required": True, "label": "Longitude column name"},
        "severity_col": {"type": "string", "label": "Severity column (optional)"},
        "severity_map": {
            "type": "string",
            "label": 'Severity mapping JSON, e.g. {"1":"fatal","2":"serious","3":"minor"}',
        },
        "date_col": {"type": "string", "label": "Date column (optional)"},
        "mode_col": {
            "type": "string",
            "label": "Involved modes column (optional; free-text matched against known modes)",
        },
        "delimiter": {"type": "string", "default": ",", "label": "Delimiter"},
        "encoding": {"type": "string", "default": "utf-8", "label": "Encoding"},
        "skip_rows": {"type": "integer", "default": 0, "label": "Header skip rows"},
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("CSV URL is required.")
        if not config.get("lat_col"):
            errors.append("Latitude column name is required.")
        if not config.get("lon_col"):
            errors.append("Longitude column name is required.")
        return errors

    def _fetch_rows(self, config):
        url = config["url"]
        encoding = config.get("encoding", "utf-8")
        delimiter = config.get("delimiter", ",")
        skip = int(config.get("skip_rows", 0) or 0)
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        text = response.content.decode(encoding, errors="replace")
        lines = text.splitlines()
        if skip:
            lines = lines[skip:]
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        return list(reader)

    def _build_severity_map(self, config):
        raw = config.get("severity_map", "")
        if raw:
            try:
                return {str(k).lower(): v for k, v in json.loads(raw).items()}
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        return DEFAULT_SEVERITY_MAP

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            rows = self._fetch_rows(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")
        smap = self._build_severity_map(config)
        preview = [_row_to_feature(r, config, smap) for r in rows[:3]]
        return ConnectorTestResult(
            True,
            f"Accident CSV OK. {len(rows)} rows found.",
            [f for f in preview if f],
        )

    def fetch(self, config, workspace=None):
        rows = self._fetch_rows(config)
        smap = self._build_severity_map(config)
        features = [f for r in rows if (f := _row_to_feature(r, config, smap)) is not None]
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _row_to_feature(row, config, severity_map):
    try:
        lat = float(str(row.get(config["lat_col"], "")).strip().replace(",", "."))
        lon = float(str(row.get(config["lon_col"], "")).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None

    severity_col = config.get("severity_col")
    severity_raw = str(row.get(severity_col, "")).strip().lower() if severity_col else ""
    severity = severity_map.get(severity_raw, "minor")

    date_col = config.get("date_col")
    date = str(row.get(date_col, "")).strip() if date_col else None
    year: int | None = None
    if date:
        # Pull a 4-digit year out of the date string if present (handles
        # YYYY, YYYY-MM, YYYY-MM-DD, DD.MM.YYYY, ...).
        for token in (date[:4], date[-4:]):
            if token.isdigit() and 1900 <= int(token) <= 2100:
                year = int(token)
                break

    mode_col = config.get("mode_col")
    involved_modes: list[str] = []
    if mode_col and row.get(mode_col):
        mode_raw = str(row[mode_col]).lower()
        for mode, aliases in _MODE_ALIASES.items():
            if any(alias in mode_raw for alias in aliases):
                involved_modes.append(mode)

    vru = any(m in involved_modes for m in ("cyclist", "pedestrian"))

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "severity": severity,
            "date": date,
            "year": year,
            "time_of_day": None,
            "weather": None,
            "involved_modes": involved_modes,
            "vulnerable_road_user": vru,
            "speed_limit": None,
            "intersection_type": None,
        },
    }
