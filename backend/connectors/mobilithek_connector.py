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
  the URL is handed to the inner connector unchanged.
- ``subscriber`` — distribution requires a Mobilithek-issued X.509 client
  certificate. The connector copies the configured ``cert_path`` and
  ``key_path`` into the inner connector's config under the shared keys
  ``client_cert_path`` / ``client_key_path``, which every inner connector
  (GTFS, GeoJSON, CSV) reads through ``connectors._http.request_kwargs``.
  Mount the certificate files into the container as Docker secrets or via
  env-injected paths; never commit the cert / key files themselves.
"""

from __future__ import annotations

import requests

from ._http import cert_from_config
from .base import (
    BaseConnector,
    CatalogEntry,
    CatalogPage,
    ConnectorTestResult,
)
from .csv_connector import CSVConnector
from .geojson_connector import GeoJSONConnector
from .gtfs_connector import GTFSConnector

SUPPORTED_FORMATS = ("gtfs", "geojson", "json", "csv")

# Map a Mobilithek distribution format_hint to the OpenMobility OS LayerKind
# value that best represents the data. Operators can still change it on the
# "Add to workspace" confirmation step.
_FORMAT_TO_LAYER = {
    "gtfs": "transit_stops",
    "geojson": "custom",
    "json": "custom",
    "csv": "custom",
}


class MobilithekConnector(BaseConnector):
    id = "mobilithek"
    display_name_de = "Mobilithek (NAP Deutschland)"
    display_name_en = "Mobilithek (German NAP)"
    description_de = (
        "Bezieht Daten vom deutschen National Access Point Mobilithek "
        "(BMDV, Nachfolger von mCLOUD). Mobilithek ist ein Gateway: die "
        "Distribution wird per URL und Format-Hinweis (gtfs, geojson, csv, "
        "json) angegeben und an den passenden Parser weitergereicht. "
        "Subscriber-Modus mit X.509-Client-Zertifikat wird unterstützt."
    )
    description_en = (
        "Fetches data from Germany's National Access Point Mobilithek "
        "(BMDV, successor to mCLOUD). Mobilithek is a gateway: pass the "
        "distribution URL and a format hint (gtfs, geojson, csv, json) and "
        "the connector dispatches to the matching parser. Subscriber mode "
        "with an X.509 client certificate is supported."
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
            "label": "Path to client certificate PEM (subscriber mode)",
        },
        "key_path": {
            "type": "string",
            "label": "Path to client private key PEM (subscriber mode)",
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
        if mode == "subscriber" and not (
            config.get("cert_path") and config.get("key_path")
        ):
            errors.append(
                "Subscriber mode requires both cert_path and key_path."
            )
        return errors

    def _inner_config(self, config: dict, url: str) -> dict:
        """Build the config dict handed to the inner parser.

        In subscriber mode the Mobilithek-level ``cert_path`` / ``key_path``
        are copied into the shared ``client_cert_path`` / ``client_key_path``
        keys so the inner connector's ``request_kwargs`` helper picks them up.
        """
        inner: dict = dict(config.get("inner_options") or {})
        inner["url"] = url
        if (config.get("mode") or "open") == "subscriber":
            inner["client_cert_path"] = config["cert_path"]
            inner["client_key_path"] = config["key_path"]
        return inner

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        cert = cert_from_config(
            {
                "client_cert_path": config.get("cert_path"),
                "client_key_path": config.get("key_path"),
            }
        )
        kwargs = {"cert": cert} if cert is not None else {}
        try:
            response = requests.head(
                config["distribution_url"],
                timeout=30,
                allow_redirects=True,
                **kwargs,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Mobilithek HEAD failed: {exc}")
        size = response.headers.get("Content-Length", "?")
        mode = (config.get("mode") or "open")
        return ConnectorTestResult(
            True,
            f"Mobilithek distribution reachable ({mode} mode). Content-Length={size}.",
        )

    def fetch(self, config, workspace=None):
        fmt = config["format_hint"].lower()
        inner = self._inner_config(config, config["distribution_url"])

        if fmt == "gtfs":
            return GTFSConnector().fetch(inner, workspace=workspace)
        if fmt in ("geojson", "json"):
            return GeoJSONConnector().fetch(inner, workspace=workspace)
        if fmt == "csv":
            return CSVConnector().fetch(inner, workspace=workspace)
        raise RuntimeError(f"Unsupported format_hint: {fmt}")

    # ------------------------------------------------------------------
    # Catalog discovery — fetches the Mobilithek DCAT-AP feed and returns
    # supported distributions as one-click "Add to workspace" candidates.
    # ------------------------------------------------------------------

    def supports_discovery(self) -> bool:
        return True

    quick_add_fields = [
        {
            "name": "name",
            "label": "Source name",
            "placeholder": "GTFS Sachsen",
            "required": True,
        },
        {
            "name": "distribution_url",
            "label": "Distribution URL",
            "placeholder": "https://download.example.com/feed.zip",
            "required": True,
        },
        {
            "name": "format_hint",
            "label": "Format (gtfs / geojson / csv / json)",
            "placeholder": "gtfs",
            "default": "gtfs",
            "required": True,
        },
    ]

    def quick_add(self, form_data, workspace=None):
        name = str(form_data.get("name") or "").strip()
        url = str(form_data.get("distribution_url") or "").strip()
        fmt = str(form_data.get("format_hint") or "").strip().lower()
        if not name or not url or not fmt:
            raise ValueError("Name, distribution URL and format are required.")
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(
                f"format must be one of {', '.join(SUPPORTED_FORMATS)} (got {fmt!r})."
            )
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("Distribution URL must start with http:// or https://.")
        return CatalogEntry(
            entry_id=f"mobilithek-custom:{url}",
            title=name,
            subtitle="custom",
            description="",
            format_hint=fmt,
            source_url=url,
            attribution="",
            license="",
            suggested_name=name,
            suggested_layer_kind=_FORMAT_TO_LAYER.get(fmt, "custom"),
            suggested_config={
                "distribution_url": url,
                "format_hint": fmt,
                "mode": "open",
            },
            badges=["custom"],
        )

    def discover(self, query=None, facets=None, workspace=None, *, _xml_bytes=None):
        from .mobilithek_catalog import CATALOG_URL, browse_catalog

        # Override chain: explicit facet > workspace.settings > settings.MOBILITHEK_CATALOG_URL > default.
        catalog_url = ""
        if facets:
            catalog_url = str(facets.get("catalog_url") or "").strip()
        if not catalog_url and workspace is not None:
            catalog_url = (workspace.settings or {}).get("mobilithek_catalog_url", "")
        if not catalog_url:
            try:
                from django.conf import settings as _dj_settings

                catalog_url = getattr(_dj_settings, "MOBILITHEK_CATALOG_URL", "") or CATALOG_URL
            except Exception:  # noqa: BLE001
                catalog_url = CATALOG_URL

        try:
            datasets = browse_catalog(
                keyword=query, catalog_url=catalog_url, _xml_bytes=_xml_bytes
            )
        except Exception as exc:  # noqa: BLE001
            return CatalogPage(
                message=f"Catalog fetch failed: {exc}",
                facets={"catalog_url": catalog_url},
            )

        existing_urls: set[str] = set()
        if workspace is not None:
            for src in workspace.data_sources.filter(source_type=self.id):
                url = (src.config or {}).get("distribution_url")
                if url:
                    existing_urls.add(url)

        supported_only = True
        if facets and str(facets.get("show_all", "")).lower() in ("1", "true", "yes"):
            supported_only = False

        format_counts: dict[str, int] = {}
        entries: list[CatalogEntry] = []
        for ds in datasets:
            best = ds.best_distribution()
            if not best:
                continue
            fmt = (best.format_hint or "").lower()
            format_counts[fmt or "unknown"] = format_counts.get(fmt or "unknown", 0) + 1
            if supported_only and fmt not in SUPPORTED_FORMATS:
                continue
            entries.append(
                CatalogEntry(
                    entry_id=ds.uid,
                    title=ds.title or ds.uid,
                    subtitle=ds.publisher,
                    description=ds.description,
                    format_hint=fmt,
                    source_url=ds.uid,
                    attribution=ds.publisher,
                    license=best.license_url,
                    suggested_name=ds.title or ds.uid,
                    suggested_layer_kind=_FORMAT_TO_LAYER.get(fmt, "custom"),
                    suggested_config={
                        "distribution_url": best.url,
                        "format_hint": fmt,
                        "mode": "open",
                        "subscription_id": ds.uid,
                    },
                    badges=ds.keywords[:4],
                    already_added=best.url in existing_urls,
                )
            )

        return CatalogPage(
            entries=entries,
            total=len(entries),
            facets={
                "format_counts": format_counts,
                "supported_only": supported_only,
                "catalog_url": catalog_url,
            },
        )
