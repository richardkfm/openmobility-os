"""
Stub connectors — interfaces defined, implementation pending.

These exist to declare our public contract early, so core code can reference
them today. Calling .fetch() raises NotImplementedError with a clear message.

Plan: full implementations in post-MVP phases. See the project plan for the
full roadmap (GTFS in Phase 9, CKAN and others in Phase 11).
"""

from .base import BaseConnector, ConnectorTestResult


class GTFSConnector(BaseConnector):
    id = "gtfs"
    display_name_de = "GTFS static (geplant)"
    display_name_en = "GTFS static (planned)"
    description_de = "Liest einen GTFS-Zip. Implementierung geplant für Phase 9."
    description_en = "Reads a GTFS zip archive. Implementation planned for Phase 9."
    config_schema = {
        "url": {"type": "string", "required": True, "label": "GTFS zip URL"},
        "agency_filter": {"type": "string", "label": "Agency ID filter (optional)"},
    }

    def test_connection(self, config, workspace=None):
        return ConnectorTestResult(
            False,
            "GTFS connector is a planned feature and not yet implemented. "
            "See CHANGELOG for progress.",
        )

    def fetch(self, config, workspace=None):
        raise NotImplementedError(
            "GTFS connector is planned for a future release. Use GeoJSON or "
            "CSV as an interim for transit stop data."
        )


class CKANConnector(BaseConnector):
    id = "ckan"
    display_name_de = "CKAN-Portal (geplant)"
    display_name_en = "CKAN portal (planned)"
    description_de = "Abruf von Ressourcen aus CKAN-Open-Data-Portalen. Geplant."
    description_en = "Fetches resources from CKAN open-data portals. Planned."
    config_schema = {
        "portal_url": {"type": "string", "required": True, "label": "CKAN portal base URL"},
        "resource_id": {"type": "string", "required": True, "label": "CKAN resource ID"},
    }

    def test_connection(self, config, workspace=None):
        return ConnectorTestResult(
            False, "CKAN connector is planned but not yet implemented."
        )

    def fetch(self, config, workspace=None):
        raise NotImplementedError("CKAN connector not yet implemented.")


class WFSConnector(BaseConnector):
    id = "wfs"
    display_name_de = "WFS-Service (geplant)"
    display_name_en = "WFS service (planned)"
    description_de = "Abruf von WFS-Layern (OGC Web Feature Service). Geplant."
    description_en = "Fetches layers from a WFS (OGC Web Feature Service). Planned."
    config_schema = {
        "url": {"type": "string", "required": True, "label": "WFS endpoint URL"},
        "layer_name": {"type": "string", "required": True, "label": "Layer name"},
        "srsname": {"type": "string", "default": "EPSG:4326", "label": "CRS"},
    }

    def test_connection(self, config, workspace=None):
        return ConnectorTestResult(
            False, "WFS connector is planned but not yet implemented."
        )

    def fetch(self, config, workspace=None):
        raise NotImplementedError("WFS connector not yet implemented.")


class RESTConnector(BaseConnector):
    id = "rest"
    display_name_de = "Generischer REST-Endpunkt (geplant)"
    display_name_en = "Generic REST endpoint (planned)"
    description_de = "JSON-REST-Endpunkt mit konfigurierbarer Pfad- und Geometrie-Abbildung. Geplant."
    description_en = "JSON REST endpoint with configurable path and geometry mapping. Planned."
    config_schema = {
        "url": {"type": "string", "required": True, "label": "Endpoint URL"},
        "headers": {"type": "object", "label": "Headers"},
        "json_path": {"type": "string", "label": "JSONPath to feature list"},
        "geometry_mapping": {"type": "object", "label": "Geometry mapping"},
    }

    def test_connection(self, config, workspace=None):
        return ConnectorTestResult(
            False, "Generic REST connector is planned but not yet implemented."
        )

    def fetch(self, config, workspace=None):
        raise NotImplementedError("Generic REST connector not yet implemented.")
