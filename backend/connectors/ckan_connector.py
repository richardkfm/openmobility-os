"""CKAN open-data portal connector.

Reaches into any CKAN-based open-data portal (GovData.de,
opendata.leipzig.de, daten.berlin.de, the EU Open Data Portal, …),
resolves a package's best-matching distribution by format preference, and
delegates parsing to the GeoJSON or CSV connector so we never duplicate
normalization logic.
"""

from __future__ import annotations

import requests

from .base import BaseConnector, ConnectorTestResult
from .csv_connector import CSVConnector
from .geojson_connector import GeoJSONConnector

DEFAULT_FORMAT_PREFERENCE = ("geojson", "json", "csv", "tsv")


class CKANConnector(BaseConnector):
    id = "ckan"
    display_name_de = "CKAN-Open-Data-Portal"
    display_name_en = "CKAN open-data portal"
    description_de = (
        "Bezieht Ressourcen aus CKAN-basierten Open-Data-Portalen "
        "(GovData.de, opendata.leipzig.de, daten.berlin.de, EU Open Data "
        "Portal …). Wählt die beste verfügbare Distribution per "
        "Format-Präferenz aus und gibt sie an den GeoJSON- oder "
        "CSV-Connector weiter."
    )
    description_en = (
        "Fetches resources from any CKAN-based open-data portal "
        "(GovData.de, opendata.leipzig.de, daten.berlin.de, the EU Open "
        "Data Portal …). Picks the best-matching distribution by format "
        "preference and delegates parsing to the GeoJSON or CSV connector."
    )

    config_schema = {
        "portal_url": {
            "type": "string",
            "required": True,
            "label": "CKAN portal base URL (e.g. https://opendata.leipzig.de)",
        },
        "package_id": {
            "type": "string",
            "label": "Package ID or name (alternative to resource_id)",
        },
        "resource_id": {
            "type": "string",
            "label": "Resource ID (skip package lookup)",
        },
        "format_preference": {
            "type": "array",
            "label": "Format preference order",
            "default": list(DEFAULT_FORMAT_PREFERENCE),
        },
        "csv_options": {
            "type": "object",
            "label": "Options forwarded to the CSV connector (lat_col, lon_col, …)",
        },
        "geojson_options": {
            "type": "object",
            "label": "Options forwarded to the GeoJSON connector",
        },
    }

    def validate_config(self, config):
        errors = []
        if not config.get("portal_url"):
            errors.append("portal_url is required.")
        if not config.get("package_id") and not config.get("resource_id"):
            errors.append("Either package_id or resource_id is required.")
        return errors

    def _action(self, portal_url: str, action: str, params: dict) -> dict:
        base = portal_url.rstrip("/")
        url = f"{base}/api/3/action/{action}"
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", True):
            raise RuntimeError(payload.get("error") or "CKAN API call failed")
        return payload.get("result") or {}

    def _resolve_resource(self, config: dict) -> dict:
        portal = config["portal_url"]
        if config.get("resource_id"):
            return self._action(portal, "resource_show", {"id": config["resource_id"]})
        package = self._action(portal, "package_show", {"id": config["package_id"]})
        resources = package.get("resources") or []
        preference = [
            f.lower()
            for f in (config.get("format_preference") or DEFAULT_FORMAT_PREFERENCE)
        ]
        for fmt in preference:
            for res in resources:
                if (res.get("format") or "").lower() == fmt and res.get("url"):
                    return res
        for res in resources:
            if res.get("url"):
                return res
        raise RuntimeError(
            f"No usable resource in CKAN package '{config.get('package_id')}'."
        )

    def _delegate(self, resource: dict, config: dict, workspace):
        fmt = (resource.get("format") or "").lower()
        url = resource.get("url")
        if not url:
            raise RuntimeError("CKAN resource has no URL.")
        if fmt in ("geojson", "json"):
            inner = dict(config.get("geojson_options") or {})
            return GeoJSONConnector().fetch({**inner, "url": url}, workspace=workspace)
        if fmt in ("csv", "tsv"):
            inner = dict(config.get("csv_options") or {})
            inner = {**inner, "url": url}
            if fmt == "tsv":
                inner.setdefault("delimiter", "\t")
            return CSVConnector().fetch(inner, workspace=workspace)
        raise RuntimeError(
            f"CKAN resource format '{fmt}' is not handled. "
            "Supported: GeoJSON, JSON, CSV, TSV."
        )

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            resource = self._resolve_resource(config)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"CKAN lookup failed: {exc}")
        url = resource.get("url") or "?"
        fmt = (resource.get("format") or "?").lower()
        name = resource.get("name") or resource.get("id") or "?"
        return ConnectorTestResult(
            True,
            f"CKAN resource resolved: name='{name}', format={fmt}, url={url}",
        )

    def fetch(self, config, workspace=None):
        resource = self._resolve_resource(config)
        return self._delegate(resource, config, workspace)
