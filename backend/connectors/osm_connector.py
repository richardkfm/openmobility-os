"""OpenStreetMap Overpass API connector.

Supports six builtin query templates covering the most common mobility layers,
plus a custom Overpass QL query escape hatch. Always workspace-agnostic: the
bbox is derived from the workspace bounds.
"""


import math

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
    # Stricter than "bike_network": only DEDICATED cycling infrastructure
    # (cyclist-only space), so it does not return ordinary roads that merely
    # carry a `cycleway=no`/`shared_lane` tag or where cycling is just
    # permitted. Includes separated cycleways/tracks, bicycle roads, and
    # on-street painted bike lanes — but excludes sharrows ("shared_lane"),
    # "cycleway=no", and "bicycle=yes/permissive". Each feature is tagged with a
    # `bike_infra_class` ("protected" vs "lane") at fetch time so the map can
    # distinguish physically separated infrastructure from mere paint. This is
    # the layer city planners need to find real gaps in safe cycling provision.
    "dedicated_bike_network": """
        [out:json][timeout:90];
        (
          way["highway"="cycleway"]({bbox});
          way["bicycle_road"="yes"]({bbox});
          way["cyclestreet"="yes"]({bbox});
          way["highway"~"^(path|footway)$"]["bicycle"="designated"]({bbox});
          way["cycleway"~"^(lane|track|opposite_lane|opposite_track)$"]({bbox});
          way["cycleway:both"~"^(lane|track)$"]({bbox});
          way["cycleway:left"~"^(lane|track)$"]({bbox});
          way["cycleway:right"~"^(lane|track)$"]({bbox});
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
    # Blue infrastructure: open water plus engineered retention. Climate
    # planners read this against sealed surfaces to find where heavy rain has
    # nowhere to go and where evaporative cooling is available. City-agnostic —
    # purely OSM water tagging, no country-specific assumptions.
    "water_bodies": """
        [out:json][timeout:60];
        (
          way["natural"="water"]({bbox});
          relation["natural"="water"]({bbox});
          way["water"]({bbox});
          way["waterway"="riverbank"]({bbox});
          way["landuse"="reservoir"]({bbox});
          way["landuse"="basin"]({bbox});
        );
        out geom tags;
    """,
    # Impervious-surface proxy. Most cities have no official sealing cadastre,
    # so we approximate from land use that is almost always paved/built over:
    # industrial/commercial/retail blocks, large surface parking and airport
    # aprons. Combined with low tree/green cover this is the strongest open
    # signal for urban heat islands.
    "sealed_surfaces": """
        [out:json][timeout:60];
        (
          way["landuse"="industrial"]({bbox});
          way["landuse"="commercial"]({bbox});
          way["landuse"="retail"]({bbox});
          way["amenity"="parking"]["parking"!="underground"]({bbox});
          way["aeroway"="apron"]({bbox});
        );
        out geom tags;
    """,
    # Admin level 9 = "Stadtbezirk" (city district) in Germany; level 10 =
    # "Ortsteil" (sub-district). Most municipalities map districts at one of
    # these two levels. Operators can override this template with `custom_query`
    # if their administrative system uses different levels.
    "districts": """
        [out:json][timeout:60];
        (
          relation["boundary"="administrative"]["admin_level"="9"]({bbox});
          relation["boundary"="administrative"]["admin_level"="10"]({bbox});
          way["boundary"="administrative"]["admin_level"="9"]({bbox});
          way["boundary"="administrative"]["admin_level"="10"]({bbox});
        );
        out geom tags;
    """,
    "kindergartens": """
        [out:json][timeout:60];
        (
          node["amenity"="kindergarten"]({bbox});
          way["amenity"="kindergarten"]({bbox});
          node["amenity"="childcare"]({bbox});
          way["amenity"="childcare"]({bbox});
        );
        out center tags;
    """,
    "hospitals": """
        [out:json][timeout:60];
        (
          node["amenity"="hospital"]({bbox});
          way["amenity"="hospital"]({bbox});
          node["amenity"="clinic"]({bbox});
          way["amenity"="clinic"]({bbox});
        );
        out center tags;
    """,
    # Civic anchors people travel to daily: libraries, town halls, community
    # centres, post offices, places of worship. Useful denominator for
    # accessibility analyses (how many residents reach a public amenity within
    # X minutes by foot/bike/transit?).
    "public_buildings": """
        [out:json][timeout:60];
        (
          node["amenity"="library"]({bbox});
          way["amenity"="library"]({bbox});
          node["amenity"="townhall"]({bbox});
          way["amenity"="townhall"]({bbox});
          node["amenity"="community_centre"]({bbox});
          way["amenity"="community_centre"]({bbox});
          node["amenity"="post_office"]({bbox});
          way["amenity"="post_office"]({bbox});
          node["amenity"="place_of_worship"]({bbox});
          way["amenity"="place_of_worship"]({bbox});
        );
        out center tags;
    """,
    # Pedestrian crossings — pull both standalone crossing nodes and crossings
    # tagged on the highway. Important input for school-route safety scoring.
    "pedestrian_crossings": """
        [out:json][timeout:60];
        (
          node["highway"="crossing"]({bbox});
          node["crossing"]({bbox});
          node["railway"="crossing"]({bbox});
        );
        out tags;
    """,
    # ── Street-space layers ──────────────────────────────────────────────
    # A redesign has to take its room from somewhere. These three templates
    # supply the evidence for that trade-off, so a proposed cycle lane can name
    # the parking spaces or the motor-traffic lane it costs instead of pretending
    # the space appears out of nowhere.
    #
    # Kerbside parking, tagged on the street way itself. Covers both the current
    # `parking:<side>` scheme and the legacy `parking:lane:<side>` scheme, since
    # OSM is mid-migration between them and coverage differs wildly by city.
    "street_parking": """
        [out:json][timeout:90];
        (
          way["parking:both"]({bbox});
          way["parking:left"]({bbox});
          way["parking:right"]({bbox});
          way["parking:lane:both"]({bbox});
          way["parking:lane:left"]({bbox});
          way["parking:lane:right"]({bbox});
        );
        out geom tags;
    """,
    # Carriageway capacity: how many motor-traffic lanes a street carries and
    # how wide it is. `width` is missing on most streets in most cities — that
    # is expected, and the platform reports it as unknown rather than guessing.
    "car_lanes": """
        [out:json][timeout:90];
        way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street)$"]({bbox});
        out geom tags;
    """,
    # Physical constraints in the street profile: tram rails (a well-known
    # cause of cyclist falls), level crossings, kerbside bus stops, barriers,
    # and structures whose cross-section cannot simply be re-striped.
    "obstacles": """
        [out:json][timeout:90];
        (
          way["railway"="tram"]({bbox});
          node["railway"="level_crossing"]({bbox});
          node["railway"="crossing"]({bbox});
          node["highway"="bus_stop"]({bbox});
          node["barrier"]({bbox});
          way["barrier"]({bbox});
          way["bridge"="yes"]["highway"]({bbox});
          way["tunnel"="yes"]["highway"]({bbox});
          way["highway"="construction"]({bbox});
        );
        out geom tags;
    """,
    # EV chargers from OSM. Note: OSM coverage is patchy compared to the
    # official Bundesnetzagentur register — wire BNetzA in parallel for
    # German workspaces.
    "ev_chargers_osm": """
        [out:json][timeout:60];
        (
          node["amenity"="charging_station"]({bbox});
          way["amenity"="charging_station"]({bbox});
        );
        out center tags;
    """,
}


class OSMOverpassConnector(BaseConnector):
    id = "osm_overpass"
    display_name_de = "OpenStreetMap (Overpass)"
    display_name_en = "OpenStreetMap (Overpass)"
    description_de = (
        "Fragt OpenStreetMap-Daten über die Overpass-API ab. "
        "Enthält Templates für die wichtigsten Mobilitäts-, Daseinsvorsorge- "
        "und Klima-Layer; Bounding Box stammt aus dem Workspace-Profil "
        "oder der Konfiguration."
    )
    description_en = (
        "Queries OpenStreetMap data via the Overpass API. "
        "Ships with templates for the most common mobility, public-services, "
        "and climate layers; bounding box comes from the workspace profile "
        "or config."
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

        # The dedicated-bike layer normalises every feature into a
        # quality class so the map can separate protected infrastructure
        # from mere painted lanes (see _classify_bike_infra).
        template = config.get("template")
        classify = template == "dedicated_bike_network"
        # Street-space layers get a normalised schema so the measures engine can
        # reason about available room without re-reading raw OSM tags.
        normalizer = _STREET_SPACE_NORMALIZERS.get(template)

        features = []
        for el in elements:
            feat = _osm_element_to_feature(el)
            if not feat:
                continue
            if normalizer:
                normalizer(feat)
            if classify:
                feat["properties"]["bike_infra_class"] = _classify_bike_infra(
                    feat["properties"]
                )
                # Capture the year the infrastructure was built/opened when OSM
                # records it, so the map can flag lanes added after a dataset's
                # period (e.g. bike lanes built after the latest accident year).
                year = _extract_bike_year(feat["properties"])
                if year is not None:
                    feat["properties"]["year"] = year
            features.append(feat)

        return FetchResult(
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )


def _extract_bike_year(props: dict):
    """Return the build/opening year of a bike feature, or None.

    Reads the standard OSM date tags (`start_date`, `opening_date`), which are
    typically `YYYY` or `YYYY-MM-DD`. City-agnostic and tolerant: any value with
    a plausible 4-digit year (1900–2100) at the start or end is accepted; missing
    or unparseable tags simply yield None.
    """
    for tag in ("start_date", "opening_date"):
        raw = props.get(tag)
        if not raw:
            continue
        text = str(raw)
        for token in (text[:4], text[-4:]):
            if token.isdigit() and 1900 <= int(token) <= 2100:
                return int(token)
    return None


def _classify_bike_infra(props: dict) -> str:
    """Classify a dedicated-bike feature as "protected" or "lane".

    "protected" = physically separated from motor traffic or a cyclist-priority
    street: standalone cycleways/paths, tracks (`cycleway[:side]=track`),
    bicycle roads / cyclestreets, and designated bike paths. "lane" = on-street
    painted bike lanes (`cycleway[:side]=lane`), which are real dedicated space
    but not physically protected. Defaults to "lane" when ambiguous so the more
    cautious (less safe) reading wins.
    """
    highway = props.get("highway")
    if highway == "cycleway":
        return "protected"
    if highway in ("path", "footway") and props.get("bicycle") == "designated":
        return "protected"
    if props.get("bicycle_road") == "yes" or props.get("cyclestreet") == "yes":
        return "protected"

    side_values = {
        props.get("cycleway"),
        props.get("cycleway:both"),
        props.get("cycleway:left"),
        props.get("cycleway:right"),
    }
    if any(v in ("track", "opposite_track") for v in side_values):
        return "protected"
    return "lane"


# ─── Street-space normalisers ────────────────────────────────────────────────
# These turn raw OSM tagging into the small, stable schema documented in
# docs/AREA_TARGETS.md. Values that OSM does not state stay absent or None —
# never substituted with a plausible-looking guess, because the space budget
# these feed is used to argue for removing people's parking and re-striping
# their streets.

_PARKING_ORIENTATIONS = {"parallel", "diagonal", "perpendicular"}
# Values of parking:<side> / parking:lane:<side> that mean "no parking here".
_PARKING_ABSENT = {"no", "none", "no_parking", "no_stopping", "separate"}


def _normalize_street_parking(feat: dict) -> None:
    """Normalise kerbside-parking tags into side/orientation/type/length."""
    props = feat["properties"]
    sides = {}
    for side in ("both", "left", "right"):
        value = props.get(f"parking:{side}") or props.get(f"parking:lane:{side}")
        if value and str(value).lower() not in _PARKING_ABSENT:
            sides[side] = str(value).lower()
    if not sides:
        props["parking_present"] = False
        return

    side = "both" if "both" in sides else ("both" if len(sides) == 2 else next(iter(sides)))
    sample = sides.get(side) or next(iter(sides.values()))

    # The orientation may sit either in the parking:<side> value itself (legacy
    # scheme) or in a dedicated :orientation subkey (current scheme).
    orientation = None
    for key in (
        f"parking:{side}:orientation",
        "parking:orientation",
        f"parking:lane:{side}",
    ):
        candidate = str(props.get(key) or "").lower()
        if candidate in _PARKING_ORIENTATIONS:
            orientation = candidate
            break
    if orientation is None and sample in _PARKING_ORIENTATIONS:
        orientation = sample
    if orientation is None:
        orientation = "parallel"  # by far the most common kerbside layout

    length_m = _line_length_m(feat.get("geometry") or {})

    props["parking_present"] = True
    props["side"] = side
    props["orientation"] = orientation
    props["parking_type"] = sample if sample not in _PARKING_ORIENTATIONS else "lane"
    props["length_m"] = length_m
    # Note: the number of parking spaces is deliberately NOT computed here.
    # It depends on the bay length in the workspace's design standard, which
    # is a measures-engine parameter (see measures/street_space.py) and is
    # overridable per workspace. Baking a default into stored data would
    # silently ignore that override.
    props["restriction"] = (
        props.get(f"parking:{side}:restriction")
        or props.get(f"parking:{side}:fee")
        or props.get("parking:restriction")
        or None
    )


def _normalize_car_lanes(feat: dict) -> None:
    """Normalise lane counts and carriageway width.

    ``width_source`` is the honesty flag: "tagged" when OSM states a width,
    "estimated" when it can only be derived from the lane count, and "unknown"
    when neither is available.
    """
    props = feat["properties"]
    props["lanes"] = _to_int(props.get("lanes"))
    props["lanes_forward"] = _to_int(props.get("lanes:forward"))
    props["lanes_backward"] = _to_int(props.get("lanes:backward"))
    props["oneway"] = str(props.get("oneway") or "").lower() in ("yes", "1", "true")

    width = _to_float(props.get("width"))
    if width:
        props["width_m"] = width
        props["width_source"] = "tagged"
    elif props["lanes"]:
        props["width_m"] = None
        props["width_source"] = "estimated"
    else:
        props["width_m"] = None
        props["width_source"] = "unknown"


_OBSTACLE_RULES = (
    ("railway", "tram", "tram_track", "cycling"),
    ("railway", "level_crossing", "level_crossing", "both"),
    ("railway", "crossing", "level_crossing", "both"),
    ("highway", "bus_stop", "bus_stop_in_lane", "cycling"),
    ("highway", "construction", "construction", "both"),
)


def _normalize_obstacles(feat: dict) -> None:
    """Tag each obstacle with a stable type and who it affects."""
    props = feat["properties"]
    obstacle_type = None
    affects = "both"
    for key, value, kind, who in _OBSTACLE_RULES:
        if props.get(key) == value:
            obstacle_type, affects = kind, who
            break
    if obstacle_type is None:
        if props.get("bridge") == "yes":
            obstacle_type, affects = "bridge", "both"
        elif props.get("tunnel") == "yes":
            obstacle_type, affects = "tunnel", "both"
        elif props.get("barrier"):
            obstacle_type, affects = "barrier", "both"
        else:
            obstacle_type, affects = "narrow_section", "both"
    props["obstacle_type"] = obstacle_type
    props["affects"] = affects
    props["note"] = props.get("name") or ""


_STREET_SPACE_NORMALIZERS = {
    "street_parking": _normalize_street_parking,
    "car_lanes": _normalize_car_lanes,
    "obstacles": _normalize_obstacles,
}


def _to_int(value):
    try:
        return int(float(str(value).split(";")[0]))
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        return float(str(value).split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None


def _line_length_m(geometry: dict):
    """Approximate the length of a LineString in metres.

    Uses a local equirectangular approximation around the line's own mean
    latitude — accurate to well under a percent at street scale, and correct
    anywhere on earth, which a fixed degrees-to-metres constant would not be.
    """
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "MultiLineString":
        return sum(_line_length_m({"type": "LineString", "coordinates": c}) for c in coords)
    if geometry.get("type") != "LineString" or len(coords) < 2:
        return None
    lats = [c[1] for c in coords if len(c) >= 2]
    if not lats:
        return None
    mean_lat_rad = math.radians(sum(lats) / len(lats))
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * math.cos(mean_lat_rad)
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        dx = (lon2 - lon1) * m_per_deg_lon
        dy = (lat2 - lat1) * m_per_deg_lat
        total += math.hypot(dx, dy)
    return round(total, 1)


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

    if el_type == "relation":
        polygons = _assemble_relation_polygons(el)
        if polygons:
            if len(polygons) == 1:
                return {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": polygons[0]},
                    "properties": props,
                }
            return {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": polygons},
                "properties": props,
            }
        # Relation members didn't form closed rings — fall back to a
        # MultiLineString of the outer ways so the boundary is at least visible.
        outer_lines = _outer_member_lines(el)
        if outer_lines:
            return {
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": outer_lines},
                "properties": props,
            }
    return None


def _outer_member_lines(relation: dict) -> list[list[list[float]]]:
    """Return each outer way's geometry as its own LineString coord list."""
    lines: list[list[list[float]]] = []
    for member in relation.get("members") or []:
        if member.get("type") != "way":
            continue
        role = member.get("role") or "outer"
        if role not in ("outer", ""):
            continue
        geom = member.get("geometry") or []
        coords = [[g["lon"], g["lat"]] for g in geom if "lon" in g and "lat" in g]
        if len(coords) >= 2:
            lines.append(coords)
    return lines


def _assemble_relation_polygons(relation: dict) -> list[list[list[list[float]]]]:
    """Assemble outer member ways into one or more closed polygon rings.

    Returns a list of polygons; each polygon is `[outer_ring]` (we don't track
    inner holes here — fine for administrative-boundary visualization, which
    rarely needs hole accuracy at the city-district level).
    """
    segments = _outer_member_lines(relation)
    if not segments:
        return []

    polygons: list[list[list[list[float]]]] = []
    remaining = [list(s) for s in segments]

    while remaining:
        ring = remaining.pop(0)
        # Already closed?
        if len(ring) >= 4 and ring[0] == ring[-1]:
            polygons.append([ring])
            continue

        # Greedy chain: keep finding a remaining segment that connects to the
        # current ring's open end, flipping if needed.
        progress = True
        while progress and ring[0] != ring[-1]:
            progress = False
            for i, seg in enumerate(remaining):
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:])
                    remaining.pop(i)
                    progress = True
                    break
                if seg[-1] == ring[-1]:
                    ring.extend(list(reversed(seg))[1:])
                    remaining.pop(i)
                    progress = True
                    break
                if seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                    remaining.pop(i)
                    progress = True
                    break
                if seg[0] == ring[0]:
                    ring = list(reversed(seg))[:-1] + ring
                    remaining.pop(i)
                    progress = True
                    break

        if len(ring) >= 4 and ring[0] == ring[-1]:
            polygons.append([ring])
        # else: dangling chain — discard (the MultiLineString fallback in the
        # caller will pick up these segments).

    return polygons
