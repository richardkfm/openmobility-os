"""GBFS (General Bikeshare Feed Specification) connector.

Reads a GBFS auto-discovery feed (``gbfs.json``) for a shared-mobility system
— bike share, e-scooters, moped or car sharing — and normalizes it to one of
two OpenMobility OS layer kinds:

- ``shared_vehicles`` — individual available vehicles (free-floating bikes,
  scooters, cars) from the ``free_bike_status`` / ``vehicle_status`` feed,
  enriched with form factor and propulsion type from ``vehicle_types`` when
  the operator publishes it.
- ``shared_stations`` — docking / hub stations from ``station_information``
  merged with live ``station_status``, carrying capacity, available vehicles,
  free docks and a planner-facing ``availability_ratio``.

GBFS is the open, vendor-neutral standard most shared-mobility operators
publish (nextbike, TIER, Lime, Bolt, Voi, car-sharing fleets, …). Using it
gives municipalities a standards-based integration point instead of scraping
or reverse-engineering operator apps. Both GBFS v2.x (language-keyed
``data``) and v3.x (flat ``data.feeds``) discovery layouts are supported.

Spec reference: https://gbfs.org / https://github.com/MobilityData/gbfs

The connector is workspace-agnostic and has no runtime dependencies beyond
``requests``. It answers the planner question "where are shared vehicles
actually available for pick-up, and where are the gaps?" — pair the resulting
point layer with the map's heatmap display mode to see concentration and
coverage holes at a glance.
"""

from __future__ import annotations

from typing import Any

import requests

from ._http import request_kwargs
from .base import BaseConnector, ConnectorTestResult, FetchResult

# Output layer kinds this connector can produce.
GBFS_LAYERS = ("shared_vehicles", "shared_stations")

# Feed names per GBFS version. v3 renamed free_bike_status → vehicle_status
# and num_bikes_available → num_vehicles_available; we accept either.
VEHICLE_FEED_NAMES = ("free_bike_status", "vehicle_status")
STATION_INFO_FEED_NAMES = ("station_information",)
STATION_STATUS_FEED_NAMES = ("station_status",)
VEHICLE_TYPES_FEED_NAMES = ("vehicle_types",)


class GBFSConnector(BaseConnector):
    id = "gbfs"
    display_name_de = "GBFS (Sharing-Mobilität: Rad/Roller/Auto)"
    display_name_en = "GBFS (shared mobility: bikes/scooters/cars)"
    description_de = (
        "Liest einen GBFS-Auto-Discovery-Feed (gbfs.json) eines "
        "Sharing-Anbieters und erzeugt je nach ``layer`` einen von zwei "
        "Layern: ``shared_vehicles`` (frei verfügbare Fahrzeuge aus "
        "free_bike_status/vehicle_status, mit Fahrzeugtyp und Antrieb) oder "
        "``shared_stations`` (Stationen aus station_information + "
        "station_status, mit Kapazität, Verfügbarkeit und "
        "Auslastungsquote). Unterstützt GBFS v2 und v3."
    )
    description_en = (
        "Reads a shared-mobility operator's GBFS auto-discovery feed "
        "(gbfs.json) and emits one of two layers depending on ``layer``: "
        "``shared_vehicles`` (available vehicles from "
        "free_bike_status/vehicle_status, with form factor and propulsion) "
        "or ``shared_stations`` (stations from station_information + "
        "station_status, with capacity, availability and an availability "
        "ratio). Supports GBFS v2 and v3."
    )

    config_schema = {
        "discovery_url": {
            "type": "string",
            "required": True,
            "label": "GBFS auto-discovery URL (gbfs.json)",
        },
        "layer": {
            "type": "string",
            "required": True,
            "enum": list(GBFS_LAYERS),
            "label": "Output layer (shared_vehicles | shared_stations)",
        },
        "language": {
            "type": "string",
            "label": (
                "Feed language code (optional; GBFS v2 feeds are keyed by "
                "language — defaults to the first one advertised)"
            ),
        },
        "default_form_factor": {
            "type": "string",
            "label": (
                "Form factor to assume when the feed omits vehicle_types "
                "(optional, e.g. 'bicycle' for a classic bike-share system)"
            ),
        },
    }

    # ------------------------------------------------------------------ API

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        if not config.get("discovery_url"):
            errors.append("GBFS discovery URL (gbfs.json) is required.")
        layer = config.get("layer")
        if not layer:
            errors.append("`layer` is required.")
        elif layer not in GBFS_LAYERS:
            errors.append(
                f"`layer` must be one of {GBFS_LAYERS}, got {layer!r}."
            )
        return errors

    def test_connection(
        self, config: dict, workspace: Any = None
    ) -> ConnectorTestResult:
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            feeds = self._discover_feeds(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Discovery failed: {exc}")

        layer = config["layer"]
        advertised = sorted(feeds.keys())
        diagnostics = {"advertised_feeds": advertised}

        try:
            features = self._build(config, feeds)
        except _MissingFeed as exc:
            return ConnectorTestResult(
                False,
                str(exc),
                diagnostics=diagnostics,
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(
                False, f"Feed parse failed: {exc}", diagnostics=diagnostics
            )

        diagnostics["feature_count"] = len(features)
        noun = "vehicles" if layer == "shared_vehicles" else "stations"
        return ConnectorTestResult(
            True,
            f"GBFS OK. {len(features)} {noun}. "
            f"Advertised feeds: {', '.join(advertised) or '—'}.",
            preview_features=features[:3],
            diagnostics=diagnostics,
        )

    def fetch(self, config: dict, workspace: Any = None) -> FetchResult:
        feeds = self._discover_feeds(config)
        features = self._build(config, feeds)

        warnings: list[str] = []
        features, clip_warning = _clip_to_bounds(features, workspace)
        if clip_warning:
            warnings.append(clip_warning)

        return FetchResult(
            feature_collection={
                "type": "FeatureCollection",
                "features": features,
            },
            record_count=len(features),
            warnings=warnings,
            diagnostics={"advertised_feeds": sorted(feeds.keys())},
        )

    # --------------------------------------------------------------- helpers

    def _get_json(self, url: str, config: dict) -> Any:
        response = requests.get(url, timeout=60, **request_kwargs(config))
        response.raise_for_status()
        return response.json()

    def _discover_feeds(self, config: dict) -> dict[str, str]:
        """Return a ``{feed_name: url}`` map from the auto-discovery feed.

        Handles both GBFS v2 (``data.<lang>.feeds``) and v3
        (``data.feeds``) layouts. The operator can pin a language with the
        ``language`` config key; otherwise the first advertised language is
        used.
        """
        discovery = self._get_json(config["discovery_url"], config)
        data = (discovery or {}).get("data") or {}
        feed_list = _extract_feed_list(data, config.get("language"))
        feeds: dict[str, str] = {}
        for entry in feed_list:
            name = entry.get("name")
            url = entry.get("url")
            if name and url:
                feeds[name] = url
        return feeds

    def _build(self, config: dict, feeds: dict[str, str]) -> list[dict]:
        layer = config["layer"]
        if layer == "shared_vehicles":
            return self._build_vehicles(config, feeds)
        if layer == "shared_stations":
            return self._build_stations(config, feeds)
        raise ValueError(f"Unknown GBFS layer: {layer!r}")

    # ---- vehicles ----------------------------------------------------

    def _build_vehicles(self, config: dict, feeds: dict[str, str]) -> list[dict]:
        url = _first_feed_url(feeds, VEHICLE_FEED_NAMES)
        if not url:
            raise _MissingFeed(
                "This system does not advertise a free_bike_status / "
                "vehicle_status feed, so it has no free-floating vehicles "
                "to map. Use layer=shared_stations instead."
            )
        payload = self._get_json(url, config)
        bikes = _feed_records(
            payload, ("bikes", "vehicles")
        )
        vehicle_types = self._load_vehicle_types(config, feeds)
        default_form = (config.get("default_form_factor") or "").strip()

        provider = _system_name(payload)
        features: list[dict] = []
        for bike in bikes:
            if not isinstance(bike, dict):
                continue
            lat = _safe_float(bike.get("lat"))
            lon = _safe_float(bike.get("lon"))
            if lat is None or lon is None:
                continue
            vt = vehicle_types.get(bike.get("vehicle_type_id"))
            form_factor = (
                (vt or {}).get("form_factor") or default_form or "unknown"
            )
            props = {
                "vehicle_id": bike.get("bike_id") or bike.get("vehicle_id") or "",
                "form_factor": form_factor,
                "is_reserved": _as_bool(bike.get("is_reserved")),
                "is_disabled": _as_bool(bike.get("is_disabled")),
                "provider": provider,
            }
            if vt:
                props["vehicle_type"] = vt.get("name") or ""
                props["propulsion_type"] = vt.get("propulsion_type") or ""
            if bike.get("current_range_meters") is not None:
                props["current_range_meters"] = _safe_float(
                    bike.get("current_range_meters")
                )
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            )
        return features

    def _load_vehicle_types(
        self, config: dict, feeds: dict[str, str]
    ) -> dict[str, dict]:
        url = _first_feed_url(feeds, VEHICLE_TYPES_FEED_NAMES)
        if not url:
            return {}
        try:
            payload = self._get_json(url, config)
        except Exception:  # noqa: BLE001 — vehicle_types is optional enrichment
            return {}
        out: dict[str, dict] = {}
        for vt in _feed_records(payload, ("vehicle_types",)):
            if isinstance(vt, dict) and vt.get("vehicle_type_id") is not None:
                out[vt["vehicle_type_id"]] = vt
        return out

    # ---- stations ----------------------------------------------------

    def _build_stations(self, config: dict, feeds: dict[str, str]) -> list[dict]:
        info_url = _first_feed_url(feeds, STATION_INFO_FEED_NAMES)
        if not info_url:
            raise _MissingFeed(
                "This system does not advertise a station_information feed, "
                "so it has no stations to map. Use layer=shared_vehicles "
                "instead."
            )
        info_payload = self._get_json(info_url, config)
        stations = _feed_records(info_payload, ("stations",))

        status_by_id: dict[str, dict] = {}
        status_url = _first_feed_url(feeds, STATION_STATUS_FEED_NAMES)
        if status_url:
            try:
                status_payload = self._get_json(status_url, config)
                for st in _feed_records(status_payload, ("stations",)):
                    if isinstance(st, dict) and st.get("station_id") is not None:
                        status_by_id[st["station_id"]] = st
            except Exception:  # noqa: BLE001 — status is enrichment, info is enough
                status_by_id = {}

        provider = _system_name(info_payload)
        features: list[dict] = []
        for station in stations:
            if not isinstance(station, dict):
                continue
            lat = _safe_float(station.get("lat"))
            lon = _safe_float(station.get("lon"))
            if lat is None or lon is None:
                continue

            status = status_by_id.get(station.get("station_id"), {})
            capacity = _as_int(station.get("capacity"))
            available = _as_int(
                _first_present(
                    status,
                    ("num_bikes_available", "num_vehicles_available"),
                )
            )
            docks = _as_int(status.get("num_docks_available"))

            ratio = None
            if capacity and available is not None and capacity > 0:
                ratio = round(available / capacity, 3)

            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "station_id": station.get("station_id") or "",
                        "name": station.get("name") or "",
                        "address": station.get("address") or "",
                        "capacity": capacity,
                        "num_vehicles_available": available,
                        "num_docks_available": docks,
                        # Planner signal: a persistently low ratio marks a
                        # station that runs empty — a candidate for more
                        # vehicles or rebalancing.
                        "availability_ratio": ratio,
                        "is_renting": _as_bool(status.get("is_renting")),
                        "is_returning": _as_bool(status.get("is_returning")),
                        "provider": provider,
                    },
                }
            )
        return features


# ----------------------------------------------------------------- parsing


class _MissingFeed(Exception):
    """Raised when a required GBFS sub-feed is not advertised."""


def _extract_feed_list(data: dict, language: str | None) -> list[dict]:
    """Pull the ``feeds`` list out of a GBFS ``data`` block.

    GBFS v3 puts feeds directly under ``data.feeds``; v2 nests them per
    language under ``data.<lang>.feeds``.
    """
    if not isinstance(data, dict):
        return []
    # v3 flat layout.
    if isinstance(data.get("feeds"), list):
        return data["feeds"]
    # v2 language-keyed layout.
    if language and isinstance(data.get(language), dict):
        return data[language].get("feeds") or []
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("feeds"), list):
            return value["feeds"]
    return []


def _feed_records(payload: Any, keys: tuple[str, ...]) -> list:
    """Return the record list from a GBFS feed's ``data`` block.

    Looks under ``data.<key>`` for the first matching key.
    """
    data = (payload or {}).get("data") or {}
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _system_name(payload: Any) -> str:
    """Best-effort provider label from a feed's metadata, if present."""
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str):
            return name
    return ""


def _first_feed_url(feeds: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in feeds:
            return feeds[name]
    return None


def _first_present(record: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in record:
            return record[key]
    return None


def _clip_to_bounds(features: list[dict], workspace: Any) -> tuple[list[dict], str]:
    """Keep only point features inside the workspace bounds.

    Mirrors the bbox behaviour of the other point connectors: if the bounds
    clip every record (e.g. a mis-aligned demo workspace), keep the unclipped
    set and return a warning rather than silently emitting an empty layer.
    """
    bounds = getattr(workspace, "bounds", None) if workspace else None
    if not bounds:
        return features, ""
    west, south, east, north = bounds.extent  # (minx, miny, maxx, maxy)

    inside: list[dict] = []
    for feat in features:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) != 2:
            continue
        lon, lat = coords
        if west <= lon <= east and south <= lat <= north:
            inside.append(feat)

    if features and not inside:
        return features, (
            "Every shared-mobility record fell outside the workspace bounds — "
            "imported the unclipped feed. Check the workspace bounding box."
        )
    return inside, ""


# ----------------------------------------------------------------- utils


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return None
