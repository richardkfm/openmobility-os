"""GeoJSON URL connector — fetches and normalizes a FeatureCollection."""

from typing import Any

import requests

from .base import BaseConnector, ConnectorTestResult, FetchResult


class GeoJSONConnector(BaseConnector):
    id = "geojson_url"
    display_name_de = "GeoJSON-URL"
    display_name_en = "GeoJSON URL"
    description_de = (
        "Lädt eine GeoJSON-FeatureCollection von einer URL. Optional: Properties "
        "umbenennen, filtern oder auf bestimmte Typen beschränken."
    )
    description_en = (
        "Fetches a GeoJSON FeatureCollection from a URL. Optional property "
        "renaming, filtering, or geometry type restriction."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "GeoJSON URL"},
        "property_rename": {
            "type": "object",
            "label": "Rename properties (old → new)",
        },
        "keep_properties": {
            "type": "array",
            "label": "Keep only these properties (optional)",
        },
        "allowed_geometry_types": {
            "type": "array",
            "label": "Restrict to geometry types (optional)",
        },
    }

    def validate_config(self, config):
        if not config.get("url"):
            return ["GeoJSON URL is required."]
        return []

    def _fetch_raw(self, url: str) -> dict:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.json()

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            data = self._fetch_raw(config["url"])
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Fetch failed: {exc}")

        features = _as_feature_list(data)
        preview = features[:3] if features else []
        return ConnectorTestResult(
            True,
            f"GeoJSON OK. Found {len(features)} features.",
            preview,
        )

    def fetch(self, config, workspace=None):
        data = self._fetch_raw(config["url"])
        features = _as_feature_list(data)

        keep = set(config.get("keep_properties") or [])
        rename = config.get("property_rename") or {}
        allowed_types = set(config.get("allowed_geometry_types") or [])

        normalized = []
        for feat in features:
            geom = feat.get("geometry") or {}
            if allowed_types and geom.get("type") not in allowed_types:
                continue
            props = feat.get("properties") or {}
            if keep:
                props = {k: v for k, v in props.items() if k in keep}
            if rename:
                props = {rename.get(k, k): v for k, v in props.items()}
            normalized.append(
                {"type": "Feature", "geometry": geom, "properties": props}
            )

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": normalized},
            record_count=len(normalized),
        )


def _as_feature_list(data):
    if not isinstance(data, dict):
        return []
    if data.get("type") == "FeatureCollection":
        return data.get("features", [])
    if data.get("type") == "Feature":
        return [data]
    return []
