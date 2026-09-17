"""OpenStreetMap Overpass API connector.

Supports the builtin query templates in OVERPASS_TEMPLATES below, covering the
common mobility, street-space and pedestrian-space layers, plus a custom
Overpass QL query escape hatch. Always workspace-agnostic: the bbox is derived
from the workspace bounds, so the same template works for any municipality.
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
    #
    # `out geom tags` and not `out tags`: Overpass's `tags` verbosity prints ids
    # and tags *without* node coordinates, and a crossing with no coordinates is
    # dropped on the floor by _osm_element_to_feature. The layer looked healthy
    # and stored nothing.
    "pedestrian_crossings": """
        [out:json][timeout:60];
        (
          node["highway"="crossing"]({bbox});
          node["crossing"]({bbox});
          node["railway"="crossing"]({bbox});
        );
        out geom tags;
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
    #
    # The barrier match is deliberately narrow. `barrier=*` in OSM also covers
    # every fence, wall, hedge and kerb in a city — mapping all of them would
    # bury the handful that actually decide whether a cycle lane can be built
    # under thousands of garden fences. Only barriers that stand in a route or
    # force a detour are collected.
    "obstacles": """
        [out:json][timeout:90];
        (
          way["railway"="tram"]({bbox});
          node["railway"="level_crossing"]({bbox});
          node["railway"="crossing"]({bbox});
          node["highway"="bus_stop"]({bbox});
          node["barrier"~"^(bollard|cycle_barrier|block|chicane|planter)$"]({bbox});
          node["barrier"~"^(gate|lift_gate|swing_gate|kissing_gate|stile)$"]({bbox});
          node["barrier"~"^(jersey_barrier|height_restrictor|debris)$"]({bbox});
          way["barrier"~"^(cycle_barrier|block|chicane|jersey_barrier)$"]({bbox});
          way["bridge"="yes"]["highway"]({bbox});
          way["tunnel"="yes"]["highway"]({bbox});
          way["highway"="construction"]({bbox});
        );
        out geom tags;
    """,
    # ── Pedestrian space and off-street parking ──────────────────────────
    # The counterpart to the street-space layers above: where the city stores
    # its cars when they are not moving, and where people can walk.
    #
    # Off-street car parks *with their footprint*. The lighter `parking`
    # template above asks for `out center` and so yields a pin per car park,
    # which answers "where are they" but not "how big". This one carries the
    # geometry, so a lot's area — and from it, in the measures layer, its
    # likely capacity — can be worked out. It is a much heavier query, which
    # is why it is a separate template rather than a change to `parking`:
    # workspaces that only want pins should not start paying for rings.
    "parking_lots": """
        [out:json][timeout:90];
        (
          way["amenity"="parking"]({bbox});
          relation["amenity"="parking"]({bbox});
        );
        out geom tags;
    """,
    # Footways and sidewalks. OSM maps pedestrian space two incompatible ways
    # and coverage differs wildly by city, so both schemes are collected:
    # separate ways (`highway=footway`, `pedestrian`, `steps`, foot-designated
    # paths) and sidewalk tags carried on the carriageway itself
    # (`sidewalk=both/left/right`). A city that maps one and not the other is
    # the normal case, not the exception.
    "footways": """
        [out:json][timeout:90];
        (
          way["highway"~"^(footway|pedestrian|steps|living_street)$"]({bbox});
          way["highway"="path"]["foot"~"^(designated|yes)$"]({bbox});
          way["sidewalk"]({bbox});
          way["sidewalk:both"]({bbox});
          way["sidewalk:left"]({bbox});
          way["sidewalk:right"]({bbox});
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

# Barriers you have to climb over or squeeze through. They obstruct a person on
# foot — and a wheelchair or a pushchair absolutely — while a cyclist dismounts
# and carries on. `affects="walking"` has been a documented value since the
# area-targets doc was written; these are the features that finally emit it.
_WALKING_BARRIERS = {"kissing_gate", "stile"}


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
            barrier = str(props.get("barrier")).lower()
            obstacle_type = "barrier"
            affects = "walking" if barrier in _WALKING_BARRIERS else "both"
        else:
            obstacle_type, affects = "narrow_section", "both"
    props["obstacle_type"] = obstacle_type
    props["affects"] = affects
    props["note"] = props.get("name") or ""


# ─── Pedestrian-space and parking-lot normalisers ────────────────────────────

# `access` values that mean the public may park here. Anything else — private,
# permit-only, a customer car park — is still stored, because a planner
# counting the city's parking supply wants to know it exists, but it is
# labelled so it can be filtered out.
_PUBLIC_ACCESS = {"yes", "public", "permissive", "designated"}
_CUSTOMER_ACCESS = {"customers", "customer"}
_PRIVATE_ACCESS = {"private", "no", "permit", "residents", "employees"}

_PARKING_FORMS = {
    "surface",
    "multi-storey",
    "underground",
    "rooftop",
    "carports",
    "garage_boxes",
    "street_side",
    "lane",
}


def _normalize_parking_lots(feat: dict) -> None:
    """Normalise an off-street car park into form, access, area and capacity.

    ``capacity_source`` is the honesty flag, and it has only two values:
    "tagged" when OSM states a capacity, "unknown" when it does not. The
    number of spaces is deliberately NOT derived from the area here. Square
    metres per space depends on the layout standard in force, which is a
    measures-engine parameter overridable per workspace (see
    measures/parking_estimate.py) — baking a default into stored data would
    silently ignore that override, the same reason _normalize_street_parking
    refuses to count kerbside bays.
    """
    props = feat["properties"]

    capacity = _to_int(props.get("capacity"))
    props["capacity"] = capacity
    props["capacity_source"] = "tagged" if capacity is not None else "unknown"

    form = str(props.get("parking") or "").lower()
    props["parking_form"] = form if form in _PARKING_FORMS else None

    access = str(props.get("access") or "").lower()
    if not access:
        props["access_class"] = "unknown"
    elif access in _PUBLIC_ACCESS:
        props["access_class"] = "public"
    elif access in _CUSTOMER_ACCESS:
        props["access_class"] = "customers"
    elif access in _PRIVATE_ACCESS:
        props["access_class"] = "private"
    else:
        props["access_class"] = "unknown"

    fee = str(props.get("fee") or "").lower()
    props["fee"] = True if fee in ("yes", "true") else (False if fee in ("no", "false") else None)

    props["levels"] = _to_int(props.get("parking:levels") or props.get("levels"))
    props["surface"] = props.get("surface") or None
    props["name"] = props.get("name") or ""
    props["area_m2"] = _polygon_area_m2(feat.get("geometry") or {})


# Values of `sidewalk` / `sidewalk:<side>` that mean "surveyed, and there is
# none here".
_SIDEWALK_ABSENT = {"no", "none"}
_SIDEWALK_PRESENT = {"yes", "both", "left", "right"}

# `separate` is neither. It means the pavement exists and is mapped as a way of
# its own, so the carriageway carries no evidence about its quality — only a
# pointer to where that evidence lives. Reading it as an absence would mark the
# streets in the best-mapped cities on Earth as having no pavement at all, which
# is the single worst thing a walkability score could say.
_SIDEWALK_SEPARATE = {"separate"}

# Highway values that are pedestrian space in their own right, where asking
# "does it have a sidewalk?" is the wrong question.
_FOOT_PRIORITY_HIGHWAYS = {"footway", "pedestrian", "steps", "path", "living_street"}

# ... of which these two are shared space: a carriageway people on foot may use
# for its full width, rather than a footway alongside one. Worth keeping apart,
# because "no pavement here" means something entirely different on a living
# street than it does on a through road.
_SHARED_SPACE_HIGHWAYS = {"pedestrian", "living_street"}


def _normalize_footways(feat: dict) -> None:
    """Normalise pedestrian space from either OSM sidewalk scheme.

    ``footway_present`` is three-state on purpose. ``True`` means a footway is
    recorded, ``False`` means the street was surveyed and has none, and
    ``None`` means OSM is silent. Collapsing the last two would turn every
    unmapped street into a hostile one, which is a claim the data does not
    support — a surveyed absence is evidence, silence is not.

    ``sidewalk=separate`` is a fourth case and reads as ``None`` with
    ``sides="separate"``: the pavement exists, it is simply mapped as a way of
    its own, so this feature holds a pointer rather than a reading.

    ``width_source`` is likewise only ever "tagged" or "unknown". A carriageway
    width can be estimated from a lane count; there is no equivalent inference
    for a pavement, so this normaliser never invents one.
    """
    props = feat["properties"]
    highway = str(props.get("highway") or "").lower()

    if highway in _FOOT_PRIORITY_HIGHWAYS:
        _normalize_separate_footway(props, highway)
    else:
        _normalize_street_sidewalk(props)

    props["highway"] = highway or None
    props["shared_space"] = highway in _SHARED_SPACE_HIGHWAYS
    props["surface"] = props.get("surface") or None
    props["smoothness"] = props.get("smoothness") or None
    props["lit"] = _yes_no(props.get("lit"))
    props["tactile_paving"] = _yes_no(props.get("tactile_paving"))
    props["incline_pct"] = _incline_pct(props.get("incline"))
    props["is_steps"] = highway == "steps"
    props["step_count"] = _to_int(props.get("step_count"))
    props["length_m"] = _line_length_m(feat.get("geometry") or {})


def _normalize_separate_footway(props: dict, highway: str) -> None:
    """A footway, path or pedestrian street mapped as a way of its own."""
    props["foot_scheme"] = "separate_way"

    access = str(props.get("foot") or "").lower()
    if highway in ("footway", "pedestrian", "steps"):
        props["foot_access"] = access or "designated"
    else:
        props["foot_access"] = access or "unknown"

    # A way explicitly closed to people on foot is a surveyed absence.
    props["footway_present"] = props["foot_access"] != "no"
    props["sides"] = "both" if props["footway_present"] else "none"

    width = _to_float(props.get("width"))
    props["width_m"] = width if width and width > 0 else None
    props["width_source"] = "tagged" if props["width_m"] else "unknown"


def _normalize_street_sidewalk(props: dict) -> None:
    """A carriageway carrying `sidewalk=*` / `sidewalk:<side>=*` tags."""
    props["foot_scheme"] = "street_tag"
    props["foot_access"] = str(props.get("foot") or "").lower() or "unknown"

    present_sides = set()
    surveyed = False
    separate = False

    # Only a value we actually recognise counts as a survey. An unexpected one
    # is not evidence that there is no pavement — it is evidence that we do not
    # understand the tag, which is a different thing and must stay "unknown".
    combined = str(props.get("sidewalk") or "").lower()
    if combined in _SIDEWALK_PRESENT:
        surveyed = True
        present_sides.update(("left", "right") if combined in ("yes", "both") else [combined])
    elif combined in _SIDEWALK_ABSENT:
        surveyed = True
    elif combined in _SIDEWALK_SEPARATE:
        separate = True

    for side in ("both", "left", "right"):
        value = str(props.get(f"sidewalk:{side}") or "").lower()
        if value in _SIDEWALK_PRESENT:
            surveyed = True
            present_sides.update(("left", "right") if side == "both" else [side])
        elif value in _SIDEWALK_ABSENT:
            surveyed = True
        elif value in _SIDEWALK_SEPARATE:
            separate = True

    if present_sides:
        props["footway_present"] = True
        props["sides"] = "both" if len(present_sides) == 2 else next(iter(present_sides))
    elif separate:
        # A pointer, not a reading — and it outranks a `no` on the other side,
        # because one side being mapped separately still means a pavement is
        # there to find. `None` keeps the street out of every "surveyed" count;
        # `sides` carries the pointer so a scorer knows to go looking for it.
        props["footway_present"] = None
        props["sides"] = "separate"
    elif surveyed:
        props["footway_present"] = False
        props["sides"] = "none"
    else:
        props["footway_present"] = None
        props["sides"] = "unknown"

    # Sidewalk widths hang off the side they describe; take the narrowest
    # stated one, since the tightest pavement is what constrains a walk.
    widths = []
    for key in (
        "sidewalk:width",
        "sidewalk:both:width",
        "sidewalk:left:width",
        "sidewalk:right:width",
    ):
        width = _to_float(props.get(key))
        if width and width > 0:
            widths.append(width)
    props["width_m"] = min(widths) if widths else None
    props["width_source"] = "tagged" if widths else "unknown"


_KERB_VALUES = {"flush", "lowered", "raised", "no"}


def _normalize_pedestrian_crossings(feat: dict) -> None:
    """Normalise a crossing node into what a walk actually depends on.

    Three-state throughout, for the same reason ``_normalize_footways`` is:
    ``crossing:markings=no`` is a survey saying the paint is not there, while
    an absent tag says only that nobody looked. A scorer that treats those
    alike punishes the unmapped and the unsafe identically.
    """
    props = feat["properties"]

    crossing = str(props.get("crossing") or "").lower()
    markings = str(props.get("crossing:markings") or "").lower()
    signals = str(props.get("crossing:signals") or "").lower()
    railway = str(props.get("railway") or "").lower()

    has_signals = _yes_no(signals)
    if has_signals is None:
        if crossing == "traffic_signals" or props.get("traffic_signals"):
            has_signals = True
        elif crossing in ("uncontrolled", "marked", "unmarked", "zebra"):
            # A crossing surveyed as one of these kinds is surveyed as not
            # signalised — that is evidence, not silence.
            has_signals = False
    props["has_signals"] = has_signals

    if railway in ("crossing", "level_crossing"):
        kind = "level_crossing"
    elif has_signals:
        kind = "traffic_signals"
    elif markings == "no" or crossing == "unmarked":
        kind = "unmarked"
    elif markings or crossing in ("marked", "zebra", "uncontrolled"):
        # Any other markings value is a marking, `surface` (a change of paving
        # rather than paint) included.
        kind = "marked"
    elif str(props.get("crossing:island") or "").lower() == "yes":
        kind = "island"
    else:
        kind = "unknown"
    props["crossing_kind"] = kind

    props["island"] = _yes_no(props.get("crossing:island"))
    props["tactile_paving"] = _yes_no(props.get("tactile_paving"))
    kerb = str(props.get("kerb") or "").lower()
    props["kerb"] = kerb if kerb in _KERB_VALUES else None
    props["crossing_ref"] = props.get("crossing_ref") or None


# ─── Speed limits ────────────────────────────────────────────────────────────

# OSM records a speed limit in whatever the local law and local habit produce:
# a bare number in km/h, a number in mph, the word `walk`, the word `none`, or a
# country-coded zone like `DE:urban`. Nothing downstream can compare those as
# strings, so they are parsed once, here.
_MPH_TO_KMH = 1.609344

# The speed of a walking pace, which is what `maxspeed=walk` means. It is a
# named speed rather than a measured one, so it gets its own source value.
_WALK_KMH = 7.0


def _maxspeed_kmh(value):
    """Parse an OSM `maxspeed` value into ``(km/h, source)``.

    ``source`` is the honesty flag:

    ``"tagged"``      — a real number, converted to km/h if it was in mph
    ``"tagged_walk"`` — ``maxspeed=walk``; a named speed, but still a survey
    ``"unlimited"``   — ``maxspeed=none``; **km/h is None, never 0**, or an
                        unrestricted road would score as the calmest street
                        in the city
    ``"implicit"``    — a zone like ``DE:urban``; see below
    ``"unparsed"``    — something we do not recognise
    ``"unknown"``     — the tag is absent

    An implicit zone is deliberately **not** resolved to a number here. What
    ``urban`` means is a question of national law, and a table of country
    defaults baked into core code is exactly the coupling this project forbids.
    The zone is preserved instead, and a workspace supplies its own numbers.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None, "unknown"
    if text == "none":
        return None, "unlimited"
    if text == "walk":
        return _WALK_KMH, "tagged_walk"

    if "mph" in text:
        number = _to_float(text.replace("mph", " ").strip())
        if number is not None and number > 0:
            return round(number * _MPH_TO_KMH, 1), "tagged"
        return None, "unparsed"

    if ":" in text:
        # A country-coded zone, e.g. "de:urban", "nz:rural", "gb:nsl_single".
        return None, "implicit"

    number = _to_float(text)
    if number is not None and number > 0:
        return round(number, 1), "tagged"
    return None, "unparsed"


def _normalize_streets_with_speed(feat: dict) -> None:
    """Normalise a speed-limited street so its limit can actually be compared."""
    props = feat["properties"]
    raw = props.get("maxspeed")
    kmh, source = _maxspeed_kmh(raw)

    props["maxspeed_raw"] = str(raw) if raw not in (None, "") else None
    props["maxspeed_kmh"] = kmh
    props["maxspeed_source"] = source
    props["maxspeed_zone"] = props["maxspeed_raw"].lower() if source == "implicit" else None

    props["highway"] = str(props.get("highway") or "").lower() or None
    props["lanes"] = _to_int(props.get("lanes"))
    props["oneway"] = str(props.get("oneway") or "").lower() in ("yes", "1", "true")
    props["length_m"] = _line_length_m(feat.get("geometry") or {})


def _yes_no(value):
    """Tri-state reading of a yes/no tag: True, False, or None for silence."""
    text = str(value or "").lower()
    if text in ("yes", "true", "1"):
        return True
    if text in ("no", "false", "0"):
        return False
    return None


def _incline_pct(value):
    """Percent gradient from an `incline` tag, or None if it states no number.

    OSM also allows `up` / `down`, which say a slope exists but not how steep;
    those carry no number, so they yield None rather than a fabricated one.
    """
    text = str(value or "").strip().rstrip("%")
    parsed = _to_float(text)
    return abs(parsed) if parsed is not None else None


_STREET_SPACE_NORMALIZERS = {
    "street_parking": _normalize_street_parking,
    "car_lanes": _normalize_car_lanes,
    "obstacles": _normalize_obstacles,
    "parking_lots": _normalize_parking_lots,
    "footways": _normalize_footways,
    "pedestrian_crossings": _normalize_pedestrian_crossings,
    "streets_with_speed": _normalize_streets_with_speed,
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


def _polygon_area_m2(geometry: dict):
    """Approximate the area of a Polygon / MultiPolygon in square metres.

    Same local equirectangular approach as :func:`_line_length_m`, around the
    ring's own mean latitude: accurate well inside a percent at car-park scale
    and correct anywhere on earth, which a fixed constant would not be.
    Interior rings (a building inside a car park, say) are subtracted.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "MultiPolygon":
        total = sum(
            _polygon_area_m2({"type": "Polygon", "coordinates": poly}) or 0.0
            for poly in coords
        )
        return round(total, 1)
    if gtype != "Polygon" or not coords:
        return None

    lats = [c[1] for ring in coords for c in ring if len(c) >= 2]
    if not lats:
        return None
    mean_lat_rad = math.radians(sum(lats) / len(lats))
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * math.cos(mean_lat_rad)

    area = 0.0
    for index, ring in enumerate(coords):
        projected = [
            (c[0] * m_per_deg_lon, c[1] * m_per_deg_lat) for c in ring if len(c) >= 2
        ]
        ring_area = _shoelace_area(projected)
        # The first ring is the outline; any further ring is a hole in it.
        area += ring_area if index == 0 else -ring_area
    return round(max(area, 0.0), 1)


def _shoelace_area(ring):
    """Absolute area of a projected ring. Winding order does not matter."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


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
