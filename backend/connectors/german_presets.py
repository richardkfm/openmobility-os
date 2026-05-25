"""German federal data-source presets.

Thin wrappers over the generic CSV and REST connectors that encode the
format-specific quirks (column names, encodings, JSON paths, geometry
mappings) of four important German open-data APIs. Operators only need to
supply the download URL; the connector handles the rest.

All four are "sugar" — the same results are achievable with the generic
``csv`` or ``rest`` connector plus the right config. These presets exist
purely to lower the onboarding barrier for German municipalities.
"""

from __future__ import annotations

from .base import BaseConnector, ConnectorTestResult
from .csv_connector import CSVConnector
from .rest_connector import RESTConnector


# ============================================================================
# Bundesnetzagentur Ladesäulenregister
# ============================================================================


class BNetzAChargingConnector(BaseConnector):
    """Bundesnetzagentur Ladesäulenregister — every public EV charger in Germany.

    Published as a semicolon-delimited CSV (cp1252) with columns
    ``Breitengrad`` / ``Längengrad``. Updated weekly.
    License: DL-DE BY 2.0.
    """

    id = "bnetza_charging"
    display_name_de = "Bundesnetzagentur — Ladesäulenregister"
    display_name_en = "Bundesnetzagentur — EV charging register"
    description_de = (
        "Jeder öffentliche Ladepunkt in Deutschland (BNetzA, wöchentlich "
        "aktualisiert, DL-DE BY 2.0). Nur Download-URL angeben — "
        "Spalten, Trennzeichen und Encoding sind vorausgefüllt."
    )
    description_en = (
        "Every public EV charger in Germany (BNetzA, updated weekly, "
        "DL-DE BY 2.0). Just supply the download URL — columns, "
        "delimiter, and encoding are pre-filled."
    )

    config_schema = {
        "url": {
            "type": "string",
            "required": True,
            "label": "CSV download URL (from bundesnetzagentur.de)",
        },
    }

    def validate_config(self, config):
        if not config.get("url"):
            return ["url is required."]
        return []

    def _inner_config(self, config):
        return {
            "url": config["url"],
            "delimiter": ";",
            "encoding": "cp1252",
            "lat_col": "Breitengrad",
            "lon_col": "Längengrad",
        }

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        return CSVConnector().test_connection(self._inner_config(config), workspace)

    def fetch(self, config, workspace=None):
        return CSVConnector().fetch(self._inner_config(config), workspace)


# ============================================================================
# Umweltbundesamt (UBA) Luftqualität
# ============================================================================

UBA_STATIONS_URL = "https://www.umweltbundesamt.de/api/air_data/v3/stations/json"


class UBAAirQualityConnector(BaseConnector):
    """Umweltbundesamt Luftqualität — official air-quality monitoring stations.

    Returns station metadata (location, active components, network) from the
    UBA REST API. The default URL points at the public station list; operators
    can override it with a more specific endpoint.
    License: DL-DE BY 2.0.
    """

    id = "uba_air"
    display_name_de = "Umweltbundesamt — Luftqualitätsstationen"
    display_name_en = "Umweltbundesamt — air quality stations"
    description_de = (
        "Offizielle Luftqualitäts-Messstationen (UBA REST API, DL-DE BY 2.0). "
        "Standard-URL ist vorausgefüllt — nur bei Bedarf ändern."
    )
    description_en = (
        "Official air-quality monitoring stations (UBA REST API, DL-DE BY 2.0). "
        "Default URL is pre-filled — change only if needed."
    )

    config_schema = {
        "url": {
            "type": "string",
            "default": UBA_STATIONS_URL,
            "label": "UBA API URL (default: station list)",
        },
    }

    def validate_config(self, config):
        return []

    def _inner_config(self, config):
        return {
            "url": config.get("url") or UBA_STATIONS_URL,
            "json_path": "data",
            "geometry_mapping": {"lat": "station_latitude", "lon": "station_longitude"},
            "keep_properties": [
                "station_name", "station_code", "station_city",
                "station_type", "station_setting", "network_name",
            ],
        }

    def test_connection(self, config, workspace=None):
        return RESTConnector().test_connection(self._inner_config(config), workspace)

    def fetch(self, config, workspace=None):
        return RESTConnector().fetch(self._inner_config(config), workspace)


# ============================================================================
# Deutscher Wetterdienst (DWD) climate stations
# ============================================================================


class DWDClimateConnector(BaseConnector):
    """DWD OpenData — climate stations with temperature / heat-day indicators.

    Reads station metadata + annual climate indicators from DWD's open-data
    CSV files (semicolon-separated, latin-1). The operator supplies the URL
    to the specific product file (e.g. annual hot-days count per station).
    License: free reuse per DWD "Geschäftsbedingungen".
    """

    id = "dwd_climate"
    display_name_de = "DWD — Klimastationen"
    display_name_en = "DWD — climate stations"
    description_de = (
        "DWD-Open-Data-Klimastationen (Hitzetage, Sommertage, Temperatur). "
        "URL zum gewünschten Produktfile angeben — Trennzeichen und "
        "Encoding sind vorausgefüllt."
    )
    description_en = (
        "DWD open-data climate stations (hot days, summer days, temperature). "
        "Supply the URL to the desired product file — delimiter and encoding "
        "are pre-filled."
    )

    config_schema = {
        "url": {
            "type": "string",
            "required": True,
            "label": "DWD product CSV URL",
        },
        "lat_col": {
            "type": "string",
            "default": "geoBreite",
            "label": "Latitude column",
        },
        "lon_col": {
            "type": "string",
            "default": "geoLaenge",
            "label": "Longitude column",
        },
    }

    def validate_config(self, config):
        if not config.get("url"):
            return ["url is required."]
        return []

    def _inner_config(self, config):
        return {
            "url": config["url"],
            "delimiter": ";",
            "encoding": "latin-1",
            "lat_col": config.get("lat_col") or "geoBreite",
            "lon_col": config.get("lon_col") or "geoLaenge",
        }

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        return CSVConnector().test_connection(self._inner_config(config), workspace)

    def fetch(self, config, workspace=None):
        return CSVConnector().fetch(self._inner_config(config), workspace)


# ============================================================================
# BASt Dauerzählstellen (automatic traffic counts)
# ============================================================================


class BASTCountsConnector(BaseConnector):
    """BASt Dauerzählstellen — automatic traffic count stations (federal roads).

    Reads the annual aggregate CSV published by the Bundesanstalt für
    Straßenwesen. Semicolon-delimited, latin-1, with columns ``Breite``
    and ``Laenge`` for coordinates.
    License: DL-DE BY 2.0.
    """

    id = "bast_counts"
    display_name_de = "BASt — Dauerzählstellen (Verkehrszählung)"
    display_name_en = "BASt — permanent count stations (traffic)"
    description_de = (
        "Automatische Verkehrszählstellen auf Bundesstraßen und Autobahnen "
        "(BASt, jährliche Aggregate, DL-DE BY 2.0). Nur Download-URL angeben."
    )
    description_en = (
        "Automatic traffic count stations on federal roads (BASt, annual "
        "aggregates, DL-DE BY 2.0). Just supply the download URL."
    )

    config_schema = {
        "url": {
            "type": "string",
            "required": True,
            "label": "BASt CSV download URL",
        },
    }

    def validate_config(self, config):
        if not config.get("url"):
            return ["url is required."]
        return []

    def _inner_config(self, config):
        return {
            "url": config["url"],
            "delimiter": ";",
            "encoding": "latin-1",
            "lat_col": "Breite",
            "lon_col": "Laenge",
        }

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        return CSVConnector().test_connection(self._inner_config(config), workspace)

    def fetch(self, config, workspace=None):
        return CSVConnector().fetch(self._inner_config(config), workspace)
