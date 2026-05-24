"""OGC WFS (Web Feature Service) connector.

Fetches a layer from any OGC-compliant WFS endpoint as GeoJSON. Works
with every German state geoportal (Geoportal Sachsen, Geoportal NRW,
Geoportal Bayern, …), the federal BKG WFS, BBSR, road-noise (Umgebungslärm)
WFS layers, and any other WFS 1.1+ server that supports
``outputFormat=application/json``.

When a workspace with bounds is supplied, the workspace bbox is sent as
a BBOX filter so the request stays small.
"""

from __future__ import annotations

import requests
from django.conf import settings

from .base import BaseConnector, ConnectorTestResult, FetchResult

DEFAULT_VERSION = "2.0.0"
DEFAULT_SRS = "EPSG:4326"
DEFAULT_OUTPUT = "application/json"


class WFSConnector(BaseConnector):
    id = "wfs"
    display_name_de = "OGC WFS-Dienst"
    display_name_en = "OGC WFS service"
    description_de = (
        "Bezieht Layer von OGC-WFS-Diensten (z. B. BKG, Geoportal Sachsen, "
        "Geoportal NRW, Umgebungslärm). Liefert GeoJSON; nutzt automatisch "
        "die Workspace-Bounding-Box als BBOX-Filter, sofern vorhanden."
    )
    description_en = (
        "Fetches a layer from any OGC WFS service (BKG, Geoportal Sachsen, "
        "Geoportal NRW, road-noise maps, …). Returns GeoJSON; if a "
        "workspace with bounds is supplied, its bbox is added as a BBOX "
        "filter automatically."
    )

    config_schema = {
        "url": {"type": "string", "required": True, "label": "WFS endpoint URL"},
        "layer_name": {
            "type": "string",
            "required": True,
            "label": "typeName / layer name",
        },
        "version": {
            "type": "string",
            "default": DEFAULT_VERSION,
            "label": "WFS version (default 2.0.0)",
        },
        "srsname": {
            "type": "string",
            "default": DEFAULT_SRS,
            "label": "Output CRS",
        },
        "output_format": {
            "type": "string",
            "default": DEFAULT_OUTPUT,
            "label": "outputFormat (default application/json)",
        },
        "cql_filter": {
            "type": "string",
            "label": "CQL filter (optional, GeoServer-style)",
        },
        "max_features": {
            "type": "integer",
            "label": "Maximum feature count (optional safety limit)",
        },
        "use_workspace_bbox": {
            "type": "boolean",
            "default": True,
            "label": "Restrict to workspace bbox when available",
        },
    }

    def validate_config(self, config):
        errors = []
        if not config.get("url"):
            errors.append("WFS endpoint URL is required.")
        if not config.get("layer_name"):
            errors.append("layer_name (typeName) is required.")
        return errors

    def _build_params(self, config: dict, workspace) -> dict:
        version = config.get("version") or DEFAULT_VERSION
        srsname = config.get("srsname") or DEFAULT_SRS
        # WFS 2.0.0 uses TYPENAMES; 1.x uses TYPENAME. We send both — servers
        # ignore the one they don't recognize.
        params = {
            "service": "WFS",
            "version": version,
            "request": "GetFeature",
            "typeNames": config["layer_name"],
            "typeName": config["layer_name"],
            "srsName": srsname,
            "outputFormat": config.get("output_format") or DEFAULT_OUTPUT,
        }
        if config.get("cql_filter"):
            params["CQL_FILTER"] = config["cql_filter"]
        max_features = config.get("max_features")
        if max_features:
            # WFS 2.0 uses count, 1.x uses maxFeatures.
            params["count"] = int(max_features)
            params["maxFeatures"] = int(max_features)
        if (
            config.get("use_workspace_bbox", True)
            and workspace is not None
            and getattr(workspace, "bounds", None) is not None
            and not config.get("cql_filter")
        ):
            b = workspace.bounds.extent  # (minx, miny, maxx, maxy) = (W, S, E, N)
            params["bbox"] = f"{b[0]},{b[1]},{b[2]},{b[3]},{srsname}"
        return params

    def _headers(self) -> dict:
        version = getattr(settings, "PLATFORM_VERSION", "0.0.0")
        repo_url = getattr(
            settings, "PROJECT_REPO_URL", "https://github.com/richardkfm/openmobility-os"
        )
        return {
            "User-Agent": f"OpenMobilityOS/{version} (+{repo_url})",
            "Accept": "application/json",
        }

    def _call(self, config, workspace) -> dict:
        response = requests.get(
            config["url"],
            params=self._build_params(config, workspace),
            headers=self._headers(),
            timeout=120,
        )
        response.raise_for_status()
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "json" not in ctype and not response.text.lstrip().startswith("{"):
            raise RuntimeError(
                "Server did not return JSON. Set output_format to a value the "
                f"server supports (got Content-Type='{ctype}')."
            )
        return response.json()

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            data = self._call(config, workspace)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"WFS call failed: {exc}")
        features = data.get("features") or []
        return ConnectorTestResult(
            True,
            f"WFS OK. Found {len(features)} features.",
            features[:3],
        )

    def fetch(self, config, workspace=None):
        data = self._call(config, workspace)
        features = data.get("features") or []
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )
