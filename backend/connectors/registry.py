"""Connector registry — maps source_type ids to connector instances."""

from .base import BaseConnector
from .csv_connector import CSVConnector
from .geojson_connector import GeoJSONConnector
from .manual_connector import ManualConnector
from .osm_connector import OSMOverpassConnector
from .stubs import CKANConnector, GTFSConnector, RESTConnector, WFSConnector

_REGISTRY: dict[str, BaseConnector] = {}


def register(connector: BaseConnector) -> None:
    _REGISTRY[connector.id] = connector


def get_connector(source_type: str) -> BaseConnector:
    return _REGISTRY[source_type]


def list_connectors() -> list[BaseConnector]:
    return list(_REGISTRY.values())


for _connector in [
    CSVConnector(),
    GeoJSONConnector(),
    OSMOverpassConnector(),
    ManualConnector(),
    GTFSConnector(),
    CKANConnector(),
    WFSConnector(),
    RESTConnector(),
]:
    register(_connector)
