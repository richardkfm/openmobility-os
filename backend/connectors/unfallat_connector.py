"""Unfallatlas connector — German Federal Statistics Office accident data.

Reads the Destatis Unfallatlas CSV format and normalises it to the OpenMobility
OS standard accident property schema. The original Destatis files are
semicolon-delimited with column names like ``XGCSWGS84``/``YGCSWGS84`` and
``IstSonstige``. Re-published mirrors often switch to comma-delimited CSV with
renamed columns (``LON``/``LAT``, ``IstSonstig``, ``STRZUSTAND``) — both
layouts are accepted via column aliases and delimiter auto-detection.

Add this source from the data hub's "Add data source" form: paste a CSV/ZIP
URL or upload a file. The authoritative **nationwide** download (covers every
German municipality, including e.g. Leipzig/Sachsen) is published per year at:

  https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/
      Unfallorte2023_EPSG25832_CSV.zip   (swap the year as needed)

The data is nationwide; on sync it is automatically clipped to the workspace's
bounding box.

License: dl-de/by-2-0 (Datenlizenz Deutschland – Namensnennung)
"""

import csv
import io

from ._http import extract_member_if_zip, fetch_bytes
from .base import BaseConnector, ConnectorTestResult, FetchResult

SEVERITY_MAP = {"1": "fatal", "2": "serious", "3": "minor"}

# Each mode flag may appear under either its original Destatis name or the
# mfdz-style abbreviation (without the trailing 'e'). Mode flag column values
# are "1" when the given mode was involved and "0" otherwise.
MODE_FLAGS = [
    (("IstRad",), "cyclist"),
    (("IstPKW",), "car"),
    (("IstFuss",), "pedestrian"),
    (("IstKrad",), "motorbike"),
    (("IstGkfz",), "truck"),
    (("IstSonstige", "IstSonstig"), "other"),
]

# Column aliases (canonical name → all names we accept, case-insensitive).
LON_ALIASES = ("XGCSWGS84", "LON", "LONGITUDE", "LNG")
LAT_ALIASES = ("YGCSWGS84", "LAT", "LATITUDE")
WEATHER_ALIASES = ("USTRZUSTAND", "STRZUSTAND")


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
        "delimiter": {
            "type": "string",
            "label": "CSV delimiter (auto-detected when blank: ',' or ';')",
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
        """Returns (rows, fieldnames, meta) — meta carries the resolved
        delimiter/encoding and the zip member name (if any) so callers can
        surface them in diagnostics."""
        url = config["url"]
        encoding = config.get("encoding", "utf-8")
        content = fetch_bytes(url, config, timeout=120)
        content, archive_member = extract_member_if_zip(
            content, extensions=(".csv", ".txt"), return_member_name=True
        )
        text = content.decode(encoding, errors="replace")
        delimiter = _resolve_delimiter(text, config.get("delimiter"))
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
        meta = {
            "delimiter": delimiter,
            "encoding": encoding,
            "archive_member": archive_member,
            "byte_size": len(content),
        }
        return rows, fieldnames, meta

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
            rows, fieldnames, meta = self._fetch_rows(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")

        diagnostics = dict(meta)
        diagnostics.update({
            "row_count": len(rows),
            "columns": list(fieldnames),
            "workspace_slug": getattr(workspace, "slug", None),
        })

        present_lower = {f.strip().lower() for f in fieldnames}
        missing = []
        if not any(a.lower() in present_lower for a in LON_ALIASES):
            missing.append(f"longitude ({'/'.join(LON_ALIASES)})")
        if not any(a.lower() in present_lower for a in LAT_ALIASES):
            missing.append(f"latitude ({'/'.join(LAT_ALIASES)})")
        if "ukategorie" not in present_lower:
            missing.append("UKATEGORIE")
        if missing:
            diagnostics["missing_columns"] = missing
            return ConnectorTestResult(
                False,
                (
                    f"Missing required columns: {missing}. "
                    f"Found: {fieldnames[:24]}"
                ),
                diagnostics=diagnostics,
            )

        # Build all features so we get an accurate coordinate range and an
        # unbiased "inside bounds" percentage. Destatis files are sorted by
        # state (ULAND); the previous "first 50 rows" sample was almost
        # always Schleswig-Holstein, hiding mismatches for southern cities.
        bbox = self._resolve_bbox(config, workspace)
        all_features = [
            f for r in rows if (f := _row_to_feature(r, None)) is not None
        ]
        coord_range = _coord_range(all_features)
        diagnostics["coord_range"] = coord_range  # (west, south, east, north)
        diagnostics["valid_geometry_count"] = len(all_features)

        bounds_extent = None
        inside_count = None
        if bbox is not None:
            bounds_extent = list(bbox)
            inside_count = sum(
                1 for f in all_features if _point_in_bbox(f, bbox)
            )
            diagnostics["workspace_bounds"] = bounds_extent
            diagnostics["inside_bounds_count"] = inside_count
            if all_features:
                diagnostics["inside_bounds_pct"] = round(
                    100.0 * inside_count / len(all_features), 1
                )

        # Map preview: spread sample across the file so we don't bias toward
        # one state. Up to 200 points.
        preview = _evenly_sampled(all_features, 200)
        diagnostics["preview_total"] = len(preview)

        message = f"Unfallatlas CSV OK. {len(rows)} rows parsed."
        if bbox is not None:
            if inside_count == 0 and len(all_features) > 0:
                message += (
                    " None of them fall inside the workspace bounds — the sync"
                    " will fall back to importing the full dataset. Check that"
                    " your workspace polygon matches the geographic area the"
                    " file covers."
                )
            elif inside_count is not None:
                message += (
                    f" {inside_count} of {len(all_features)} points"
                    f" ({diagnostics.get('inside_bounds_pct', 0)}%) inside"
                    " workspace bounds."
                )

        return ConnectorTestResult(
            True,
            message,
            preview,
            diagnostics=diagnostics,
        )

    def fetch(self, config, workspace=None):
        rows, _, meta = self._fetch_rows(config)
        bbox = self._resolve_bbox(config, workspace)
        warnings = []

        clipped = [f for r in rows if (f := _row_to_feature(r, bbox)) is not None]
        unclipped_count = sum(
            1 for r in rows if _row_to_feature(r, None) is not None
        )

        # Auto-fallback: if a workspace clip drops every row but the file
        # itself parses fine, import the full dataset so the user sees
        # something on the map. Operators almost always prefer this over a
        # silent zero-result sync — they can re-narrow the bounds later.
        features = clipped
        if bbox is not None and len(clipped) == 0 and unclipped_count > 0:
            features = [
                f for r in rows if (f := _row_to_feature(r, None)) is not None
            ]
            warnings.append(
                "Workspace bounds dropped every row — imported the full "
                "dataset instead so the data is visible. Adjust the "
                "workspace bounds, then re-sync to apply the clip."
            )

        diagnostics = dict(meta)
        diagnostics.update({
            "row_count": len(rows),
            "valid_geometry_count": unclipped_count,
            "inside_bounds_count": len(clipped) if bbox is not None else None,
            "workspace_bounds": list(bbox) if bbox is not None else None,
            "imported_unclipped": bool(warnings),
        })
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
            warnings=warnings,
            diagnostics=diagnostics,
        )


def _row_to_feature(row, bbox=None):
    lon = _safe_float_de(_lookup(row, LON_ALIASES))
    lat = _safe_float_de(_lookup(row, LAT_ALIASES))
    if lon is None or lat is None:
        return None
    if bbox is not None:
        west, south, east, north = bbox
        if not (west <= lon <= east and south <= lat <= north):
            return None

    severity_code = str(_lookup(row, ("UKATEGORIE",)) or "").strip()
    severity = SEVERITY_MAP.get(severity_code, "minor")

    involved_modes = [
        mode
        for aliases, mode in MODE_FLAGS
        if str(_lookup(row, aliases) or "0").strip() == "1"
    ]
    vru = any(m in involved_modes for m in ("cyclist", "pedestrian"))

    year_str = str(_lookup(row, ("UJAHR",)) or "").strip()
    month = str(_lookup(row, ("UMONAT",)) or "").strip().zfill(2)
    date = f"{year_str}-{month}" if year_str and month else None
    year_int: int | None
    try:
        year_int = int(year_str) if year_str else None
    except ValueError:
        year_int = None

    hour_str = str(_lookup(row, ("USTUNDE",)) or "").strip()
    time_of_day = _time_of_day(hour_str)

    weather_code = str(_lookup(row, WEATHER_ALIASES) or "").strip()
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
    utyp = str(_lookup(row, ("UTYP1",)) or "").strip()
    return {"1": "t_junction", "2": "crossing", "3": "roundabout"}.get(utyp, "none")


def _lookup(row, aliases):
    """Return the first non-empty cell from *row* whose column name (case-
    insensitive) matches one of *aliases*. ``None`` when nothing matches.

    Cached lookup map is built on first call per row dict — the cost is a
    handful of microseconds for the few hundred rows in a typical Destatis
    annual export and keeps the alias rule self-contained here rather than
    leaking into csv.DictReader.
    """
    lookup_map = row.get("__alias_index__")
    if lookup_map is None:
        lookup_map = {k.lower(): k for k in row if isinstance(k, str)}
        row["__alias_index__"] = lookup_map
    for alias in aliases:
        original = lookup_map.get(alias.lower())
        if original is None:
            continue
        value = row.get(original)
        if value not in (None, ""):
            return value
    return None


def _resolve_delimiter(text: str, override: str | None) -> str:
    """Pick ',' or ';' based on the header line. Honour an explicit override."""
    if override:
        return override
    first_line = text.split("\n", 1)[0]
    semi = first_line.count(";")
    comma = first_line.count(",")
    if semi == 0 and comma == 0:
        return ";"
    return ";" if semi >= comma else ","


def _coord_range(features):
    """Return (west, south, east, north) of all point features, or None."""
    if not features:
        return None
    lons = [f["geometry"]["coordinates"][0] for f in features]
    lats = [f["geometry"]["coordinates"][1] for f in features]
    return [min(lons), min(lats), max(lons), max(lats)]


def _point_in_bbox(feature, bbox):
    lon, lat = feature["geometry"]["coordinates"]
    west, south, east, north = bbox
    return west <= lon <= east and south <= lat <= north


def _evenly_sampled(items, k):
    """Return at most *k* items spaced evenly across *items*. Preserves
    chronological / geographic spread so a map preview isn't biased toward
    the start of the file (Destatis sorts by ULAND = state)."""
    n = len(items)
    if n <= k:
        return list(items)
    step = n / k
    return [items[int(i * step)] for i in range(k)]
