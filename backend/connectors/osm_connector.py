"""OpenStreetMap Overpass API connector.

Supports six builtin query templates covering the most common mobility layers,
plus a custom Overpass QL query escape hatch. Always workspace-agnostic: the
bbox is derived from the workspace bounds.
"""


import requests
from django.conf import settings

from .base import BaseConnector, ConnectorTestResult, FetchResult

OVERPASS_TEMPLATES: dict[str, str] = {
    "streets": """
        [out:json][timeout:60];
        way["highway"]({bbox});
        out geom tags;
    """,
    "streets_with_speed": """
        [out:json][timeout:60];
        way["highway"]["maxspeed"]({bbox});
        out geom tags;
    """,
    "bike_network": """
        [out:json][timeout:60];
        (
          way["highway"="cycleway"]({bbox});
          way["cycleway"]({bbox});
          way["cycleway:left"]({bbox});
          way["cycleway:right"]({bbox});
          way["cycleway:both"]({bbox});
          way["bicycle"="designated"]({bbox});
        );
        out geom tags;
    """,
    "transit_stops": """
        [out:json][timeout:60];
        (
          node["public_transport"="stop_position"]({bbox});
          node["highway"="bus_stop"]({bbox});
          node["railway"="tram_stop"]({bbox});
        );
        out tags;
    """,
    "schools": """
        [out:json][timeout:60];
        (
          node["amenity"="school"]({bbox});
          way["amenity"="school"]({bbox});
        );
        out center tags;
    """,
    "parking": """
        [out:json][timeout:60];
        (
          node["amenity"="parking"]({bbox});
          way["amenity"="parking"]({bbox});
        );
        out center tags;
    """,
    "trees": """
        [out:json][timeout:60];
        node["natural"="tree"]({bbox});
        out tags;
    """,
    "parks_and_green": """
        [out:json][timeout:60];
        (
          way["leisure"="park"]({bbox});
          way["landuse"="grass"]({bbox});
          way["landuse"="meadow"]({bbox});
          way["leisure"="garden"]({bbox});
        );
        out geom tags;
    """,
}


class OSMOverpassConnector(BaseConnector):
    id = "osm_overpass"
    display_name_de = "OpenStreetMap (Overpass)"
    display_name_en = "OpenStreetMap (Overpass)"
    description_de = (
        "Fragt OpenStreetMap-Daten über die Overpass-API ab. "
        "Enthält sechs Templates für die wichtigsten Mobilitäts-Layer; "
        "Bounding Box stammt aus dem Workspace-Profil oder der Konfiguration."
    )
    description_en = (
        "Queries OpenStreetMap data via the Overpass API. "
        "Ships with six templates for the most common mobility layers; "
        "bounding box comes from the workspace profile or config."
    )

    config_schema = {
        "template": {
            "type": "string",
            "enum": list(OVERPASS_TEMPLATES.keys()) + ["custom"],
            "label": "Template (or 'custom')",
            "required": True,
        },
        "custom_query": {
            "type": "string",
            "label": "Custom Overpass QL (when template = custom)",
        },
        "bbox": {
            "type": "string",
            "label": "Bounding box 'south,west,north,east' (optional — defaults to workspace bounds)",
        },
    }

    def validate_config(self, config):
        errors = []
        tpl = config.get("template")
        if not tpl:
            errors.append("Template is required.")
        elif tpl == "custom" and not config.get("custom_query"):
            errors.append("custom_query is required when template = custom.")
        elif tpl != "custom" and tpl not in OVERPASS_TEMPLATES:
            errors.append(f"Unknown template: {tpl}")
        return errors

    def _resolve_bbox(self, config, workspace) -> str:
        bbox = config.get("bbox")
        if bbox:
            return bbox
        if workspace and workspace.bounds:
            b = workspace.bounds.extent  # (minx, miny, maxx, maxy) = (west, south, east, north)
            # Overpass expects: south,west,north,east
            return f"{b[1]},{b[0]},{b[3]},{b[2]}"
        raise ValueError(
            "No bounding box available. Provide 'bbox' in config or set workspace.bounds."
        )

    def _build_query(self, config, workspace) -> str:
        if config.get("template") == "custom":
            return config["custom_query"]
        template = OVERPASS_TEMPLATES[config["template"]]
        bbox = self._resolve_bbox(config, workspace)
        return template.replace("{bbox}", bbox).strip()

    def _call_overpass(self, query: str) -> dict:
        endpoint = settings.OSM_OVERPASS_API
        version = getattr(settings, "PLATFORM_VERSION", "0.0.0")
        repo_url = getattr(settings, "PROJECT_REPO_URL", "https://github.com/richardkfm/openmobility-os")
        # Overpass API rejects the default python-requests User-Agent with HTTP 406.
        # It requires clients to identify themselves so operators can reach out about
        # excessive traffic. See https://dev.overpass-api.de/overpass-doc/en/preface/commons.html
        headers = {
            "User-Agent": f"OpenMobilityOS/{version} (+{repo_url})",
            "Accept": "application/json",
        }
        response = requests.post(
            endpoint, data={"data": query}, headers=headers, timeout=180
        )
        response.raise_for_status()
        return response.json()

    def test_connection(self, config, workspace=None):
        errors = self.validate_config(config)
        if errors:
            return ConnectorTestResult(False, "; ".join(errors))
        try:
            query = self._build_query(config, workspace)
        except ValueError as exc:
            return ConnectorTestResult(False, str(exc))
        try:
            data = self._call_overpass(query)
        except Exception as exc:  # noqa: BLE001
            return ConnectorTestResult(False, f"Overpass call failed: {exc}")
        elements = data.get("elements", [])
        preview = [
            _osm_element_to_feature(el) for el in elements[:3] if _osm_element_to_feature(el)
        ]
        return ConnectorTestResult(
            True,
            f"Overpass OK. Found {len(elements)} elements.",
            preview,
        )

    def fetch(self, config, workspace=None):
        query = self._build_query(config, workspace)
        data = self._call_overpass(query)
        elements = data.get("elements", [])

        features = []
        for el in elements:
            feat = _osm_element_to_feature(el)
            if feat:
                features.append(feat)

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _osm_element_to_feature(el: dict):
    """Convert an Overpass 'out geom' element into a GeoJSON feature."""
    el_type = el.get("type")
    tags = el.get("tags") or {}
    props = {"osm_id": el.get("id"), "osm_type": el_type, **tags}

    if el_type == "node":
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        }

    if el_type == "way":
        # Prefer explicit geometry from `out geom`
        geom = el.get("geometry")
        if geom:
            coords = [[g["lon"], g["lat"]] for g in geom]
            is_closed = len(coords) >= 4 and coords[0] == coords[-1]
            if is_closed and tags.get("area") != "no":
                return {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": props,
                }
            return {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
        # Fallback to center from `out center`
        center = el.get("center")
        if center:
            return {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [center["lon"], center["lat"]]},
                "properties": props,
            }
    return None
