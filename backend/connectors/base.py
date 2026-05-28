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


@dataclass
class CatalogEntry:
    """One discoverable item exposed by a connector's catalog browser.

    Returned by `BaseConnector.discover()`. The data hub renders each entry
    as a row with an "Add to workspace" button that materialises a
    `DataSource` from `suggested_*` and runs an initial sync.
    """

    entry_id: str
    title: str
    subtitle: str = ""
    description: str = ""
    format_hint: str = ""
    source_url: str = ""
    attribution: str = ""
    license: str = ""
    suggested_name: str = ""
    suggested_layer_kind: str = ""
    suggested_config: dict = field(default_factory=dict)
    badges: list = field(default_factory=list)
    already_added: bool = False


@dataclass
class CatalogPage:
    """A page of catalog entries plus open-ended faceting metadata."""

    entries: list = field(default_factory=list)
    total: int = 0
    facets: dict = field(default_factory=dict)
    message: str = ""


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

    # ------------------------------------------------------------------
    # Optional catalog discovery — implemented by connectors that have an
    # upstream catalog the operator can browse (Mobilithek DCAT-AP feed,
    # Unfallatlas year list, …).
    # ------------------------------------------------------------------

    def supports_discovery(self) -> bool:
        """Opt-in flag — True if this connector implements `discover`."""
        return False

    def discover(
        self,
        query: str | None = None,
        facets: dict | None = None,
        workspace: Any = None,
    ) -> CatalogPage:
        """Browse the connector's upstream catalog.

        Default implementation returns an empty page. Connectors that
        override `supports_discovery` to True must override this too.
        """
        return CatalogPage()

    # ------------------------------------------------------------------
    # Optional ad-hoc quick-add — lets admins enter a custom entry
    # (e.g. a year + URL for Unfallatlas, or a one-off Mobilithek
    # distribution URL) without editing config files.
    # ------------------------------------------------------------------

    quick_add_fields: list = []
    """Schema for the inline quick-add form rendered on the catalog page.

    List of dicts with ``name``, ``label``, ``placeholder``, optional
    ``required`` and ``default``. Empty list = no quick-add form.
    """

    def quick_add(self, form_data: dict, workspace: Any = None) -> CatalogEntry:
        """Validate `form_data` and return a `CatalogEntry` to materialise.

        Raise `ValueError` with a user-facing message on validation
        errors. Default implementation rejects (no quick-add support).
        """
        raise ValueError("This connector does not support quick-add.")
