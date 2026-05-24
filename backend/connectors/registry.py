"""Connector registry — maps source_type ids to connector instances."""

from .accident_connector import AccidentCSVConnector
from .base import BaseConnector
from .bikemaps_connector import BikeMapsConnector
from .ckan_connector import CKANConnector
from .csv_connector import CSVConnector
from .geojson_connector import GeoJSONConnector
from .gtfs_connector import GTFSConnector
from .manual_connector import ManualConnector
from .mobilithek_connector import MobilithekConnector
from .osm_connector import OSMOverpassConnector
from .rest_connector import RESTConnector
from .unfallat_connector import UnfallatlasConnector
from .wfs_connector import WFSConnector

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
    AccidentCSVConnector(),
    UnfallatlasConnector(),
    BikeMapsConnector(),
    GTFSConnector(),
    CKANConnector(),
    WFSConnector(),
    RESTConnector(),
    MobilithekConnector(),
]:
    register(_connector)
