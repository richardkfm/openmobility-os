"""Connector base interface.

All data source adapters in OpenMobility OS implement the same interface.
This keeps core code free of vendor assumptions — see CLAUDE.md principles.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectorTestResult:
    success: bool
    message: str
    preview_features: list = field(default_factory=list)


@dataclass
class FetchResult:
    feature_collection: dict
    record_count: int
    warnings: list = field(default_factory=list)


class BaseConnector:
    """Subclass and register via @register_connector."""

    id: str = ""
    display_name_de: str = ""
    display_name_en: str = ""
    description_de: str = ""
    description_en: str = ""

    # JSON-Schema-like dict describing the config fields — used to render the UI form.
    config_schema: dict = {}

    def validate_config(self, config: dict) -> list[str]:
        """Return list of human-readable error strings. Empty list means valid."""
        return []

    def test_connection(self, config: dict, workspace: Any = None) -> ConnectorTestResult:
        raise NotImplementedError

    def fetch(self, config: dict, workspace: Any = None) -> FetchResult:
        raise NotImplementedError
