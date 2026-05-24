"""Generic JSON REST endpoint connector.

For data sources that return JSON — either a top-level array or a JSON
object containing an array somewhere inside. The user describes:

- where in the response the feature list lives (``json_path``, dotted), and
- how to extract geometry from each feature: either ``lat`` + ``lon``
  property paths, or a single ``geojson`` property path pointing at an
  embedded GeoJSON geometry object.

Covers UBA Luftqualität, Sensor.Community, OpenChargeMap, ADAC,
Bundesnetzagentur, and most municipal endpoints that aren't behind a
CKAN catalog yet.
"""

from __future__ import annotations

from typing import Any

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult


class RESTConnector(BaseConnector):
    id = "rest"
    display_name_de = "Generischer REST/JSON-Endpunkt"
    display_name_en = "Generic REST/JSON endpoint"
    description_de = (
        "Holt eine Feature-Liste aus einem beliebigen JSON-Endpoint. "
        "Per Konfiguration werden der Pfad zur Liste und das "
        "Geometrie-Mapping (lat+lon oder eingebettete GeoJSON-Geometrie) "
        "festgelegt."
    )
    description_en = (
        "Fetches a feature list from any JSON endpoint. Config specifies "
        "the dotted path to the list and the geometry mapping "
        "(lat+lon or an embedded GeoJSON geometry)."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "Endpoint URL"},
        "headers": {"type": "object", "label": "Request headers (optional)"},
        "params": {"type": "object", "label": "Query params (optional)"},
        "json_path": {
            "type": "string",
            "label": (
                "Dotted path to the feature list "
                "(default: top-level if list, else 'features')"
            ),
        },
        "geometry_mapping": {
            "type": "object",
            "label": (
                "Geometry mapping. Either {'lat': '…', 'lon': '…'} "
                "or {'geojson': '…'}"
            ),
        },
        "keep_properties": {
            "type": "array",
            "label": "Keep only these property keys (optional)",
        },
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("url is required.")
        mapping = config.get("geometry_mapping") or {}
        if not mapping:
            errors.append("geometry_mapping is required.")
        elif not (
            ("lat" in mapping and "lon" in mapping) or "geojson" in mapping
        ):
            errors.append(
                "geometry_mapping must define either lat+lon or geojson."
            )
        return errors

    def _walk(self, data: Any, path: str | None) -> list:
        if path:
            for part in path.split("."):
                if isinstance(data, dict):
                    data = data.get(part)
                else:
                    return []
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            return data["features"]
        return []

    def _call(self, config) -> Any:
        response = requests.get(
            config["url"],
            params=config.get("params") or None,
            headers=config.get("headers") or None,
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    def _feature_from(
        self, item: dict, mapping: dict, keep: set | None
    ) -> dict | None:
        if "geojson" in mapping:
            geom = _lookup(item, mapping["geojson"])
            if not isinstance(geom, dict) or "type" not in geom:
                return None
        else:
            lat = _safe_float(_lookup(item, mapping.get("lat")))
            lon = _safe_float(_lookup(item, mapping.get("lon")))
            if lat is None or lon is None:
                return None
            geom = {"type": "Point", "coordinates": [lon, lat]}

        props = dict(item) if isinstance(item, dict) else {}
        for sentinel in mapping.values():
            if isinstance(sentinel, str) and "." not in sentinel:
                props.pop(sentinel, None)
        if keep:
            props = {k: v for k, v in props.items() if k in keep}
        return {"type": "Feature", "geometry": geom, "properties": props}

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            data = self._call(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"REST call failed: {exc}")
        items = self._walk(data, config.get("json_path"))
        mapping = config.get("geometry_mapping") or {}
        keep = set(config.get("keep_properties") or []) or None
        preview = []
        for item in items[:3]:
            if isinstance(item, dict):
                feat = self._feature_from(item, mapping, keep)
                if feat:
                    preview.append(feat)
        return ConnectorTestResult(
            True,
            f"REST OK. Found {len(items)} items.",
            preview,
        )

    def fetch(self, config, workspace=None):
        data = self._call(config)
        items = self._walk(data, config.get("json_path"))
        mapping = config.get("geometry_mapping") or {}
        keep = set(config.get("keep_properties") or []) or None

        features = []
        for item in items:
            if not isinstance(item, dict):
                continue
            feat = self._feature_from(item, mapping, keep)
            if feat:
                features.append(feat)

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _lookup(item: dict, path: str | None):
    if not path or not isinstance(item, dict):
        return None
    cur: Any = item
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _safe_float(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None
