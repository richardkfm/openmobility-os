"""Mobilithek (German National Access Point for mobility data) connector.

Mobilithek (https://mobilithek.info, operated by BMDV, successor to mCLOUD)
is Germany's official EU NAP for mobility data. It is a *gateway* portal:
each dataset is published as a distribution (GTFS zip, GeoJSON, CSV, JSON,
DATEX II XML, …) reachable via a stable download URL — sometimes openly,
sometimes behind a Mobilithek-issued X.509 client certificate.

This connector takes a chosen distribution URL plus a format hint and
dispatches to the existing parser for that format. It stays
workspace-agnostic: no Mobilithek URLs live in core code — they belong in
per-DataSource config or workspace YAML.

Two access modes:

- ``open`` (default) — distribution is reachable without authentication;
  we hand the URL to the inner connector unchanged.
- ``subscriber`` — distribution requires a Mobilithek subscriber cert.
  *Planned*: full subscriber support requires plumbing the client cert
  through the inner GTFS / CSV / GeoJSON parsers, which use
  ``requests.get`` directly. Tracked separately; open-mode datasets
  (the majority of Mobilithek's catalogue) work today.
"""

from __future__ import annotations

import requests

from .base import BaseConnector, ConnectorTestResult
from .csv_connector import CSVConnector
from .geojson_connector import GeoJSONConnector
from .gtfs_connector import GTFSConnector

SUPPORTED_FORMATS = ("gtfs", "geojson", "json", "csv")


class MobilithekConnector(BaseConnector):
    id = "mobilithek"
    display_name_de = "Mobilithek (NAP Deutschland)"
    display_name_en = "Mobilithek (German NAP)"
    description_de = (
        "Bezieht Daten vom deutschen National Access Point Mobilithek "
        "(BMDV, Nachfolger von mCLOUD). Mobilithek ist ein Gateway: die "
        "Distribution wird per URL und Format-Hinweis (gtfs, geojson, csv, "
        "json) angegeben und an den passenden Parser weitergereicht. "
        "Subscriber-Modus mit Client-Zertifikat ist geplant; offene "
        "Distributionen funktionieren bereits."
    )
    description_en = (
        "Fetches data from Germany's National Access Point Mobilithek "
        "(BMDV, successor to mCLOUD). Mobilithek is a gateway: pass the "
        "distribution URL and a format hint (gtfs, geojson, csv, json) and "
        "the connector dispatches to the matching parser. Subscriber mode "
        "with an X.509 client certificate is planned; open distributions "
        "work today."
    )

    config_schema = {
        "subscription_id": {
            "type": "string",
            "label": "Mobilithek subscription/dataset ID (optional, for attribution)",
        },
        "distribution_url": {
            "type": "string",
            "required": True,
            "label": "Distribution URL (the actual data file)",
        },
        "format_hint": {
            "type": "string",
            "enum": list(SUPPORTED_FORMATS),
            "required": True,
            "label": "Format of the distribution",
        },
        "mode": {
            "type": "string",
            "enum": ["open", "subscriber"],
            "default": "open",
            "label": "Access mode",
        },
        "cert_path": {
            "type": "string",
            "label": "Path to client certificate PEM (subscriber mode, planned)",
        },
        "key_path": {
            "type": "string",
            "label": "Path to client private key PEM (subscriber mode, planned)",
        },
        "inner_options": {
            "type": "object",
            "label": "Options forwarded to the inner parser (gtfs layer, csv lat_col, …)",
        },
    }

    def validate_config(self, config):
        errors = []
        if not config.get("distribution_url"):
            errors.append("distribution_url is required.")
        fmt = (config.get("format_hint") or "").lower()
        if fmt not in SUPPORTED_FORMATS:
            errors.append(
                f"format_hint must be one of {SUPPORTED_FORMATS} (got {fmt!r})."
            )
        mode = config.get("mode") or "open"
        if mode not in ("open", "subscriber"):
            errors.append(f"mode must be 'open' or 'subscriber' (got {mode!r}).")
        if mode == "subscriber" and not (config.get("cert_path") and config.get("key_path")):
            errors.append(
                "Subscriber mode requires both cert_path and key_path."
            )
        return errors

    def _check_subscriber_mode(self, config):
        if (config.get("mode") or "open") == "subscriber":
            raise NotImplementedError(
                "Mobilithek subscriber mode (client-certificate-protected "
                "feeds, e.g. DATEX II realtime) is not yet wired through the "
                "inner GTFS/CSV/GeoJSON parsers. Open distributions work "
                "today; subscriber support is planned."
            )

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        if (config.get("mode") or "open") == "subscriber":
            return ConnectorTestResult(
                False,
                "Mobilithek subscriber mode is not yet implemented. "
                "Open distributions are supported today.",
            )
        try:
            response = requests.head(
                config["distribution_url"],
                timeout=30,
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Mobilithek HEAD failed: {exc}")
        size = response.headers.get("Content-Length", "?")
        return ConnectorTestResult(
            True,
            f"Mobilithek distribution reachable. Content-Length={size}.",
        )

    def fetch(self, config, workspace=None):
        self._check_subscriber_mode(config)
        fmt = config["format_hint"].lower()
        inner = dict(config.get("inner_options") or {})
        url = config["distribution_url"]

        if fmt == "gtfs":
            return GTFSConnector().fetch({**inner, "url": url}, workspace=workspace)
        if fmt in ("geojson", "json"):
            return GeoJSONConnector().fetch({**inner, "url": url}, workspace=workspace)
        if fmt == "csv":
            return CSVConnector().fetch({**inner, "url": url}, workspace=workspace)
        raise RuntimeError(f"Unsupported format_hint: {fmt}")
