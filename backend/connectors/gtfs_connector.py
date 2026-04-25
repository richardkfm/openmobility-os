"""GTFS static connector.

Reads a GTFS zip archive (routes, stops, trips, stop_times, calendar, shapes)
and normalizes it to one of three OpenMobility OS layer kinds:

- ``transit_stops``   — stops enriched with accessibility, average headway,
  night service flag, and the transit modes serving each stop
- ``transit_routes``  — LineString geometry per route (from ``shapes.txt`` when
  available; falls back to the stop sequence otherwise)
- ``transit_coverage`` — circular buffer polygons (default 400 m) around each
  stop; useful for population-coverage analysis on the map

Standard GTFS reference: https://gtfs.org/schedule/reference/

The connector is workspace-agnostic and has no external runtime dependencies
beyond ``requests``; the whole archive is parsed in memory using the Python
standard library.
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult

GTFS_LAYERS = ("transit_stops", "transit_routes", "transit_coverage")

DEFAULT_COVERAGE_BUFFER_M = 400
DEFAULT_SERVICE_WINDOW_MIN = 16 * 60  # 06:00–22:00

# GTFS route_type integer → OMOS mode string
ROUTE_TYPE_TO_MODE = {
    0: "tram",
    1: "subway",
    2: "rail",
    3: "bus",
    4: "ferry",
    5: "cable_tram",
    6: "aerial_lift",
    7: "funicular",
    11: "trolleybus",
    12: "monorail",
}

# wheelchair_boarding integer → normalized accessibility string
ACCESSIBILITY_MAP = {"1": "yes", "2": "no", "0": "unknown", "": "unknown"}


class GTFSConnector(BaseConnector):
    id = "gtfs"
    display_name_de = "GTFS static (Nahverkehrsfahrplan)"
    display_name_en = "GTFS static (public transit schedule)"
    description_de = (
        "Liest ein statisches GTFS-Zip (Haltestellen, Linien, Fahrten, "
        "Stop-Times, Kalender, Shapes). Produziert je nach ``layer`` einen "
        "der drei Layer ``transit_stops`` (angereichert um Barrierefreiheit, "
        "Takt, Nachtverkehr), ``transit_routes`` (Liniengeometrie) oder "
        "``transit_coverage`` (300–500 m Einzugsbereiche je Haltestelle)."
    )
    description_en = (
        "Reads a static GTFS zip (stops, routes, trips, stop_times, calendar, "
        "shapes). Depending on ``layer`` it emits one of three layers: "
        "``transit_stops`` (enriched with accessibility, headway, night "
        "service), ``transit_routes`` (route geometry), or "
        "``transit_coverage`` (300–500 m buffer polygons per stop)."
    )

    config_schema = {
        "url": {
            "type": "string",
            "required": True,
            "label": "GTFS zip URL",
        },
        "layer": {
            "type": "string",
            "required": True,
            "enum": list(GTFS_LAYERS),
            "label": (
                "Output layer (transit_stops | transit_routes | transit_coverage)"
            ),
        },
        "agency_filter": {
            "type": "string",
            "label": "Agency ID filter (optional)",
        },
        "route_type_filter": {
            "type": "array",
            "label": (
                "Restrict to route_type codes (optional, e.g. [0,1,3] for "
                "tram/subway/bus)"
            ),
        },
        "coverage_buffer_m": {
            "type": "integer",
            "default": DEFAULT_COVERAGE_BUFFER_M,
            "label": "Coverage buffer in metres (only for layer=transit_coverage)",
        },
        "service_window_hours": {
            "type": "number",
            "default": 16,
            "label": (
                "Daytime service window in hours used for headway calculation "
                "(default 16, i.e. 06:00–22:00)"
            ),
        },
    }

    # ------------------------------------------------------------------ API

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if not config.get("url"):
            errors.append("GTFS zip URL is required.")
        layer = config.get("layer")
        if not layer:
            errors.append("`layer` is required.")
        elif layer not in GTFS_LAYERS:
            errors.append(
                f"`layer` must be one of {GTFS_LAYERS}, got {layer!r}."
            )
        buffer_m = config.get("coverage_buffer_m")
        if buffer_m is not None:
            try:
                if int(buffer_m) <= 0:
                    errors.append("coverage_buffer_m must be positive.")
            except (TypeError, ValueError):
                errors.append("coverage_buffer_m must be an integer.")
        return errors

    def test_connection(self, config: dict, workspace: Any = None) -> ConnectorTestResult:
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            archive = self._fetch_archive(config["url"])
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")
        try:
            tables = _read_tables(archive)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Archive parse failed: {exc}")

        missing = [t for t in ("stops.txt", "routes.txt") if t not in tables]
        if missing:
            return ConnectorTestResult(
                False, f"GTFS archive is missing required files: {missing}"
            )

        preview_features = self._build(tables, config)[:3]
        return ConnectorTestResult(
            True,
            (
                f"GTFS OK. {len(tables.get('stops.txt', []))} stops, "
                f"{len(tables.get('routes.txt', []))} routes, "
                f"{len(tables.get('trips.txt', []))} trips."
            ),
            preview_features,
        )

    def fetch(self, config: dict, workspace: Any = None) -> FetchResult:
        archive = self._fetch_archive(config["url"])
        tables = _read_tables(archive)
        features = self._build(tables, config)
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )

    # --------------------------------------------------------------- helpers

    def _fetch_archive(self, url: str) -> zipfile.ZipFile:
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        return zipfile.ZipFile(io.BytesIO(response.content))

    def _build(self, tables: dict[str, list[dict]], config: dict) -> list[dict]:
        layer = config.get("layer")
        agency = (config.get("agency_filter") or "").strip() or None
        route_types = _coerce_int_list(config.get("route_type_filter"))

        stops = tables.get("stops.txt", [])
        routes = tables.get("routes.txt", [])
        trips = tables.get("trips.txt", [])
        stop_times = tables.get("stop_times.txt", [])
        shapes = tables.get("shapes.txt", [])

        # Filter routes by agency / route_type before anything else so the
        # downstream lookups ignore irrelevant data entirely.
        routes = [
            r for r in routes
            if (agency is None or r.get("agency_id") == agency)
            and (not route_types or _as_int(r.get("route_type")) in route_types)
        ]
        route_ids = {r["route_id"] for r in routes}
        trips = [t for t in trips if t.get("route_id") in route_ids]
        trip_ids = {t["trip_id"] for t in trips}
        stop_times = [st for st in stop_times if st.get("trip_id") in trip_ids]

        if layer == "transit_stops":
            return _build_stops_features(stops, routes, trips, stop_times, config)
        if layer == "transit_routes":
            return _build_routes_features(stops, routes, trips, stop_times, shapes)
        if layer == "transit_coverage":
            buffer_m = int(
                config.get("coverage_buffer_m") or DEFAULT_COVERAGE_BUFFER_M
            )
            active_stop_ids = {st["stop_id"] for st in stop_times}
            return _build_coverage_features(stops, active_stop_ids, buffer_m)
        raise ValueError(f"Unknown GTFS layer: {layer!r}")


# ---------------------------------------------------------------- parsing


def _read_tables(archive: zipfile.ZipFile) -> dict[str, list[dict]]:
    """Read known GTFS text files into lists of dicts.

    Unknown files are ignored. Missing files simply don't appear in the result.
    """
    wanted = {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "calendar_dates.txt",
        "shapes.txt",
    }
    tables: dict[str, list[dict]] = {}
    names = {n.lower(): n for n in archive.namelist()}
    for name in wanted:
        real = names.get(name)
        if not real:
            continue
        with archive.open(real) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            tables[name] = [
                {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in reader
            ]
    return tables


# ---------------------------------------------------------------- stops


def _build_stops_features(
    stops: list[dict],
    routes: list[dict],
    trips: list[dict],
    stop_times: list[dict],
    config: dict,
) -> list[dict]:
    route_by_id = {r["route_id"]: r for r in routes}
    trip_route = {t["trip_id"]: t.get("route_id") for t in trips}

    service_hours = float(config.get("service_window_hours") or 16)
    service_window_min = max(service_hours, 0.1) * 60

    stop_trip_count: dict[str, int] = defaultdict(int)
    stop_modes: dict[str, set[str]] = defaultdict(set)
    stop_night: dict[str, bool] = defaultdict(bool)

    for st in stop_times:
        stop_id = st.get("stop_id")
        if not stop_id:
            continue
        stop_trip_count[stop_id] += 1

        trip_id = st.get("trip_id")
        route_id = trip_route.get(trip_id)
        route = route_by_id.get(route_id) if route_id else None
        if route is not None:
            mode = ROUTE_TYPE_TO_MODE.get(_as_int(route.get("route_type")), "other")
            stop_modes[stop_id].add(mode)

        if _is_night_time(st.get("arrival_time") or st.get("departure_time")):
            stop_night[stop_id] = True

    features: list[dict] = []
    for row in stops:
        lat = _safe_float(row.get("stop_lat"))
        lon = _safe_float(row.get("stop_lon"))
        if lat is None or lon is None:
            continue
        # GTFS location_type 1 = station (parent), 2 = entrance, 3 = generic,
        # 4 = boarding area. Only emit actual stops (0 or empty).
        location_type = (row.get("location_type") or "").strip()
        if location_type not in ("", "0"):
            continue

        stop_id = row.get("stop_id")
        daily_trips = stop_trip_count.get(stop_id, 0)
        avg_headway_min = (
            round(service_window_min / daily_trips, 1)
            if daily_trips > 0
            else None
        )
        accessibility = ACCESSIBILITY_MAP.get(
            (row.get("wheelchair_boarding") or "").strip(), "unknown"
        )
        modes = sorted(stop_modes.get(stop_id, set()))

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "stop_id": stop_id,
                    "name": row.get("stop_name") or "",
                    "code": row.get("stop_code") or "",
                    "wheelchair_boarding": accessibility,
                    "modes": modes,
                    "daily_trips": daily_trips,
                    "avg_headway_min": avg_headway_min,
                    "night_service": stop_night.get(stop_id, False),
                    "zone_id": row.get("zone_id") or "",
                },
            }
        )
    return features


def _is_night_time(hhmmss: str | None) -> bool:
    if not hhmmss:
        return False
    try:
        hours = int(hhmmss.split(":")[0])
    except (ValueError, AttributeError):
        return False
    # GTFS allows hours >= 24 to represent service that continues past midnight.
    # Fold those into the 0–23 range.
    hours = hours % 24
    return hours >= 22 or hours < 5


# ---------------------------------------------------------------- routes


def _build_routes_features(
    stops: list[dict],
    routes: list[dict],
    trips: list[dict],
    stop_times: list[dict],
    shapes: list[dict],
) -> list[dict]:
    stop_coords = {
        s["stop_id"]: (_safe_float(s.get("stop_lon")), _safe_float(s.get("stop_lat")))
        for s in stops
        if s.get("stop_id")
    }

    shape_coords: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in shapes:
        shape_id = row.get("shape_id")
        lon = _safe_float(row.get("shape_pt_lon"))
        lat = _safe_float(row.get("shape_pt_lat"))
        seq = _safe_float(row.get("shape_pt_sequence")) or 0
        if not shape_id or lat is None or lon is None:
            continue
        shape_coords[shape_id].append((seq, lon, lat))
    shape_lines = {
        sid: [(lon, lat) for _, lon, lat in sorted(points, key=lambda p: p[0])]
        for sid, points in shape_coords.items()
    }

    # Pick a representative trip per route (the first one we see, preferring
    # trips that actually reference a shape so the geometry is richer).
    trips_by_route: dict[str, list[dict]] = defaultdict(list)
    for t in trips:
        trips_by_route[t.get("route_id")].append(t)

    trip_stop_sequences: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for st in stop_times:
        trip_id = st.get("trip_id")
        seq = _as_int(st.get("stop_sequence"))
        stop_id = st.get("stop_id")
        if not trip_id or stop_id is None or seq is None:
            continue
        trip_stop_sequences[trip_id].append((seq, stop_id))

    features: list[dict] = []
    for route in routes:
        route_id = route["route_id"]
        route_trips = trips_by_route.get(route_id, [])
        if not route_trips:
            continue

        # Prefer trips with a shape — if none has one, fall back to the first.
        rep_trip = next(
            (t for t in route_trips if t.get("shape_id")), route_trips[0]
        )
        coords: list[tuple[float, float]] = []
        shape_id = rep_trip.get("shape_id")
        if shape_id and shape_id in shape_lines:
            coords = shape_lines[shape_id]
        else:
            seq = sorted(trip_stop_sequences.get(rep_trip["trip_id"], []))
            for _, stop_id in seq:
                pt = stop_coords.get(stop_id)
                if pt and pt[0] is not None and pt[1] is not None:
                    coords.append((pt[0], pt[1]))

        if len(coords) < 2:
            continue

        mode = ROUTE_TYPE_TO_MODE.get(_as_int(route.get("route_type")), "other")
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(c) for c in coords],
                },
                "properties": {
                    "route_id": route_id,
                    "short_name": route.get("route_short_name") or "",
                    "long_name": route.get("route_long_name") or "",
                    "mode": mode,
                    "route_type": _as_int(route.get("route_type")),
                    "agency_id": route.get("agency_id") or "",
                    "color": _hash_color(route.get("route_color") or ""),
                    "trip_count": len(route_trips),
                },
            }
        )
    return features


def _hash_color(hex_code: str) -> str:
    hex_code = (hex_code or "").strip().lstrip("#")
    if len(hex_code) == 6 and all(c in "0123456789abcdefABCDEF" for c in hex_code):
        return f"#{hex_code.lower()}"
    return ""


# --------------------------------------------------------------- coverage


def _build_coverage_features(
    stops: list[dict],
    active_stop_ids: set[str],
    buffer_m: int,
) -> list[dict]:
    features: list[dict] = []
    for row in stops:
        stop_id = row.get("stop_id")
        if active_stop_ids and stop_id not in active_stop_ids:
            continue
        lat = _safe_float(row.get("stop_lat"))
        lon = _safe_float(row.get("stop_lon"))
        if lat is None or lon is None:
            continue
        ring = _circle_ring(lon, lat, buffer_m, steps=36)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "stop_id": stop_id,
                    "name": row.get("stop_name") or "",
                    "buffer_m": buffer_m,
                },
            }
        )
    return features


def _circle_ring(
    lon: float, lat: float, radius_m: float, steps: int = 36
) -> list[list[float]]:
    """Approximate circle as a polygon ring in WGS84.

    Uses the flat-earth ``metres per degree`` approximation — accurate to well
    under a percent for radii up to a few kilometres at typical mid-latitudes,
    which is appropriate for transit stop coverage visualization.
    """
    lat_rad = math.radians(lat)
    lat_per_m = 1 / 110_574
    lon_per_m = 1 / max(111_320 * math.cos(lat_rad), 1e-6)
    ring: list[list[float]] = []
    for i in range(steps):
        angle = (2 * math.pi * i) / steps
        dx = math.cos(angle) * radius_m * lon_per_m
        dy = math.sin(angle) * radius_m * lat_per_m
        ring.append([lon + dx, lat + dy])
    ring.append(ring[0])
    return ring


# ----------------------------------------------------------------- utils


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_int_list(value: Any) -> list[int]:
    if not value:
        return []
    if isinstance(value, str):
        parts: Iterable[str] = (p for p in value.split(",") if p.strip())
    else:
        parts = (str(p) for p in value)
    out: list[int] = []
    for p in parts:
        n = _as_int(p)
        if n is not None:
            out.append(n)
    return out
