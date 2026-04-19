"""Manual KPI / measure connector — accepts pre-baked GeoJSON from config.

This exists so small towns or data-poor municipalities can operate the
platform with only manually maintained indicators.
"""

from .base import BaseConnector, ConnectorTestResult, FetchResult


class ManualConnector(BaseConnector):
    id = "manual"
    display_name_de = "Manuell gepflegt"
    display_name_en = "Manually maintained"
    description_de = (
        "Übernimmt eine bereits normalisierte GeoJSON-FeatureCollection direkt "
        "aus der Konfiguration. Für Orte ohne API-Datenquellen."
    )
    description_en = (
        "Takes a pre-normalized GeoJSON FeatureCollection directly from the "
        "config. For places without API data sources."
    )

    config_schema = {
        "feature_collection": {
            "type": "object",
            "required": True,
            "label": "GeoJSON FeatureCollection",
        }
    }

    def validate_config(self, config):
        fc = config.get("feature_collection")
        if not fc or fc.get("type") != "FeatureCollection":
            return ["feature_collection must be a GeoJSON FeatureCollection"]
        return []

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        features = config["feature_collection"].get("features", [])
        return ConnectorTestResult(
            True, f"OK. {len(features)} features.", features[:3]
        )

    def fetch(self, config, workspace=None):
        fc = config["feature_collection"]
        features = fc.get("features", [])
        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )
