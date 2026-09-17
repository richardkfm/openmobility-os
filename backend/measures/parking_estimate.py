"""Parked cars — how many a street or car park holds, and where they would sit.

OpenMobility OS can already price a rebuild in parking spaces. What it could not
do is show the other side of that trade: how much of a city is given over to
cars at rest. This module turns kerbside-parking tags and off-street car-park
polygons into individual car positions, so "the space cars occupy" stops being
an abstraction and becomes something a council chamber can count.

Two honesty rules govern everything here, and neither may be relaxed:

1. **A guess is never dressed as a survey.** Every estimate carries a ``basis``
   of ``"surveyed"`` (OpenStreetMap records parking here), ``"modelled"`` (we
   assumed it, because a residential street usually has a kerb people park on)
   or ``"unknown"`` (the data cannot say). The map draws the two differently and
   counts them separately.
2. **Capacity is not occupancy.** ``occupancy_rate`` defaults to 1.0 on purpose.
   "How many cars fit here" is a countable claim about geometry. "How many are
   here right now" is a second layer of fiction, and the UI says *capacity*.

Bay geometry is not restated here: the length a parked car consumes and the
width a parking lane occupies live in :mod:`measures.street_space`, which is
already the transparent, per-workspace-overridable catalogue for them. This
module adds only what that one does not cover — square metres per space in an
off-street car park, and which untagged streets are worth modelling at all.

The module is pure: no Django, no I/O, no database. It takes normalised GeoJSON
features in and returns GeoJSON out, so it can be unit-tested without PostGIS.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from random import Random
from typing import Any

from measures import street_space
from measures.geo import (
    line_length_m,
    longest_edge_bearing,
    make_inverse_projector,
    make_projector,
    point_in_ring,
    polygon_area_m2,
)

# ─── Parameters ──────────────────────────────────────────────────────────────
# Every number is a default, not a truth. A municipality whose parking standard
# differs overrides any of them via ``Workspace.settings["parking_estimate"]``,
# exactly as with the street-space catalogue. Nothing here may be hard-wired to
# one country's design guidance.
DEFAULT_PARAMS: dict[str, Any] = {
    # Square metres of car park per space, including that space's share of the
    # aisles, ramps and turning room. A bay alone is roughly 12.5 m²; the rest
    # is what makes the bay reachable.
    "lot_area_per_space_m2": {
        "surface": 25.0,
        "multi-storey": 27.5,
        "underground": 27.5,
        "rooftop": 25.0,
        "carports": 20.0,
        "garage_boxes": 20.0,
        "street_side": 20.0,
        "lane": 20.0,
        "default": 25.0,
    },
    # Which untagged streets get a modelled kerb. Anything not listed here is
    # left alone: a trunk road with no parking tags is not assumed to have a
    # parking lane, because it usually does not.
    "modelled_street_types": ["residential", "living_street", "unclassified"],
    # The assumption applied where OpenStreetMap is silent.
    "modelled_sides": 1,
    "modelled_orientation": "parallel",
    # Driveways, junctions, hydrants, bus stops and dropped kerbs eat roughly a
    # fifth of any kerb. Applied to modelled *and* surveyed kerbs, because the
    # tag says "there is parking along here", not "every metre of it is a bay".
    "kerb_coverage_factor": 0.8,
    # Do not model a five-metre stub.
    "min_modelled_length_m": 20.0,
    # Share of the capacity assumed to be occupied. 1.0 means the layer reports
    # capacity, which is what the UI says it reports. Raising or lowering this
    # turns it into an occupancy scenario, and the caller owns that claim.
    "occupancy_rate": 1.0,
    # Drawing parameters. These place the symbols; they measure nothing.
    # A way's geometry is its centreline, so a parked car sits roughly half a
    # carriageway away from it.
    "kerb_offset_m": 4.0,
    "jitter_m": 0.6,
    "source": {
        "title": "OpenMobility OS default parked-car estimation parameters",
        "note": (
            "Generic defaults for turning parking tags into car counts. "
            "Replace with the parking standard that applies in your "
            "jurisdiction via Workspace.settings['parking_estimate']."
        ),
    },
    # Marked for review in the same spirit as measures/effects.py: these are
    # plausible planning figures, not values a maintainer has checked against a
    # named standard. The UI surfaces the flag so no reader mistakes one for
    # the other.
    "needs_review": True,
}

# Above this many symbols a city-sized workspace stops being a map and starts
# being a denial-of-service on the browser. Past it the server thins the output
# and records how many cars each remaining symbol stands for — and the legend
# must then say so, because a thinned map claiming one symbol per car is a lie.
MAX_SYMBOLS = 20_000

# Access classes normalised by the parking_lots connector, in the order a
# filter UI should offer them.
ACCESS_CLASSES = ("public", "customers", "private", "unknown")

BASES = ("surveyed", "modelled")


def params_for(workspace=None) -> dict[str, Any]:
    """Merge ``Workspace.settings["parking_estimate"]`` over the defaults."""
    overrides = {}
    if workspace is not None:
        overrides = (getattr(workspace, "settings", None) or {}).get("parking_estimate") or {}
    merged = dict(DEFAULT_PARAMS)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


# ─── The estimate ────────────────────────────────────────────────────────────


@dataclass
class ParkingEstimate:
    """How many cars a place holds, and how confidently we can say so.

    ``count`` of ``None`` means *unknowable*, and is deliberately distinct from
    ``0``, which means *surveyed, and there is no parking here*. Callers must
    keep the two apart: one is an argument for syncing better data, the other is
    a finding.
    """

    count: int | None
    basis: str  # surveyed | modelled | unknown
    method: str  # machine key naming the formula used
    inputs: dict = field(default_factory=dict)
    confidence: str = "low"  # high | medium | low


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None


def _occupied(count: int, params: dict) -> int:
    rate = _to_float(params.get("occupancy_rate"))
    if rate is None:
        rate = 1.0
    return max(0, int(round(count * rate)))


def estimate_kerb(props: dict, *, params=None, street_params=None) -> ParkingEstimate:
    """Cars along a kerb OpenStreetMap has surveyed.

    ``basis`` is ``"surveyed"`` because the *parking* is recorded, not because
    the *count* is: OSM almost never tags how many bays a street has, so the
    number comes from bay geometry and the confidence says medium. Where the
    survey records an absence, the honest answer is a surveyed zero.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS

    present = props.get("parking_present")
    if present is False:
        return ParkingEstimate(
            count=0,
            basis="surveyed",
            method="tagged_absence",
            inputs={"parking_present": False},
            confidence="high",
        )
    if not present:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_parking_tags", inputs={}
        )

    length = _to_float(props.get("length_m"))
    if length is None or length <= 0:
        return ParkingEstimate(
            count=None,
            basis="unknown",
            method="no_usable_length",
            inputs={"parking_present": True},
        )

    orientation = props.get("orientation") or "parallel"
    coverage = _to_float(p.get("kerb_coverage_factor")) or 1.0
    sides = 2 if props.get("side") == "both" else 1
    per_side = street_space.estimated_parking_spaces(
        length * coverage, orientation, params=sp
    )
    if per_side is None:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_bay_length", inputs={}
        )

    return ParkingEstimate(
        count=_occupied(per_side * sides, p),
        basis="surveyed",
        method="tagged_kerb_length",
        inputs={
            "length_m": round(length, 1),
            "orientation": orientation,
            "sides": sides,
            "kerb_coverage_factor": coverage,
            "parking_type": props.get("parking_type"),
        },
        confidence="medium",
    )


def estimate_modelled_kerb(props: dict, *, params=None, street_params=None) -> ParkingEstimate:
    """Cars along a street OpenStreetMap says nothing about.

    This is the guess, and it is labelled as one everywhere it surfaces. Only
    the street classes in ``modelled_street_types`` get one, because a
    residential street almost always has a kerb people park on and a trunk road
    usually does not. A street too short to hold a bay gets a modelled zero
    rather than a fractional car.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS

    highway = str(props.get("highway") or "").lower()
    allowed = [str(h).lower() for h in (p.get("modelled_street_types") or [])]
    if highway not in allowed:
        return ParkingEstimate(
            count=None,
            basis="unknown",
            method="street_class_not_modelled",
            inputs={"highway": highway or None},
        )

    length = _to_float(props.get("length_m"))
    if length is None or length <= 0:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_usable_length", inputs={}
        )
    min_length = _to_float(p.get("min_modelled_length_m")) or 0.0
    if length < min_length:
        return ParkingEstimate(
            count=0,
            basis="modelled",
            method="below_min_modelled_length",
            inputs={"length_m": round(length, 1), "min_modelled_length_m": min_length},
            confidence="low",
        )

    orientation = p.get("modelled_orientation") or "parallel"
    coverage = _to_float(p.get("kerb_coverage_factor")) or 1.0
    try:
        sides = max(1, int(p.get("modelled_sides") or 1))
    except (TypeError, ValueError):
        sides = 1
    per_side = street_space.estimated_parking_spaces(
        length * coverage, orientation, params=sp
    )
    if per_side is None:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_bay_length", inputs={}
        )

    return ParkingEstimate(
        count=_occupied(per_side * sides, p),
        basis="modelled",
        method="modelled_kerb_length",
        inputs={
            "length_m": round(length, 1),
            "highway": highway,
            "orientation": orientation,
            "sides": sides,
            "kerb_coverage_factor": coverage,
        },
        confidence="low",
    )


def estimate_lot(props: dict, *, params=None) -> ParkingEstimate:
    """Cars in an off-street car park.

    A tagged ``capacity`` is a survey and is used verbatim. Otherwise the count
    comes from the footprint divided by square metres per space, multiplied by
    the number of levels — which is where a multi-storey's cars come from, and
    why its symbols end up stacked on one footprint.
    """
    p = params or DEFAULT_PARAMS

    capacity = props.get("capacity")
    if props.get("capacity_source") == "tagged" and capacity is not None:
        try:
            tagged = max(0, int(capacity))
        except (TypeError, ValueError):
            tagged = None
        if tagged is not None:
            return ParkingEstimate(
                count=_occupied(tagged, p),
                basis="surveyed",
                method="tagged_capacity",
                inputs={"capacity": tagged},
                confidence="high",
            )

    area = _to_float(props.get("area_m2"))
    if area is None or area <= 0:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_capacity_or_area", inputs={}
        )

    per_space_map = p.get("lot_area_per_space_m2") or {}
    form = props.get("parking_form") or "default"
    per_space = _to_float(per_space_map.get(form)) or _to_float(
        per_space_map.get("default")
    )
    if not per_space:
        return ParkingEstimate(
            count=None, basis="unknown", method="no_area_per_space", inputs={}
        )

    levels = props.get("levels")
    try:
        levels = max(1, int(levels)) if levels is not None else 1
    except (TypeError, ValueError):
        levels = 1

    return ParkingEstimate(
        count=_occupied(int(area * levels // per_space), p),
        basis="modelled",
        method="area_per_space",
        inputs={
            "area_m2": round(area, 1),
            "parking_form": props.get("parking_form"),
            "area_per_space_m2": per_space,
            "levels": levels,
        },
        confidence="medium" if props.get("parking_form") else "low",
    )


# ─── Deterministic scatter ───────────────────────────────────────────────────


def seeded_random(key) -> Random:
    """A generator whose stream depends only on ``key``.

    Uses ``zlib.crc32`` rather than Python's :func:`hash`, which is salted per
    process. With ``hash`` the cars would jump to new positions on every worker
    restart and disagree between a cached response and a fresh one — a map that
    redraws itself differently each time reads as noise, not as data.
    """
    return Random(zlib.crc32(str(key).encode("utf-8")))


def _ring_xy(ring, forward):
    return [forward(c[0], c[1]) for c in ring if len(c) >= 2]


def scatter_along_line(coords_xy, count: int, *, side: str, offset_m: float,
                       jitter_m: float, rng: Random) -> list[tuple[float, float]]:
    """Place ``count`` cars along a projected centreline, offset to one kerb.

    Points land at even intervals of arc length rather than at vertices, so a
    long straight section gets its share of cars instead of clustering them
    wherever the way happens to bend.
    """
    pts = [(float(x), float(y)) for x, y in coords_xy]
    if count <= 0 or len(pts) < 2:
        return []

    spans = []
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg <= 0:
            continue
        spans.append((total, seg, x1, y1, (x2 - x1) / seg, (y2 - y1) / seg))
        total += seg
    if total <= 0 or not spans:
        return []

    out: list[tuple[float, float]] = []
    for i in range(count):
        # Half-step in, so the first and last car are not sitting on the
        # junction at either end of the way.
        target = total * (i + 0.5) / count
        start, seg, x1, y1, ux, uy = spans[-1]
        for span in spans:
            if span[0] + span[1] >= target:
                start, seg, x1, y1, ux, uy = span
                break
        along = target - start
        px = x1 + ux * along
        py = y1 + uy * along
        # Left normal of the direction of travel.
        nx, ny = -uy, ux
        if side == "both":
            sign = 1.0 if i % 2 == 0 else -1.0
        elif side == "right":
            sign = -1.0
        elif side == "left":
            sign = 1.0
        else:
            sign = 1.0 if i % 2 == 0 else -1.0
        jx = rng.uniform(-jitter_m, jitter_m)
        jy = rng.uniform(-jitter_m, jitter_m)
        out.append((px + nx * offset_m * sign + jx, py + ny * offset_m * sign + jy))
    return out


def scatter_in_polygon(rings_xy, count: int, *, spacing_m: float,
                       rng: Random) -> list[tuple[float, float]]:
    """Lay ``count`` cars out in rows aligned to a projected car park.

    The grid is rotated onto the lot's own longest edge before it is cut to
    shape. Rows parallel to the lot read as a car park; a random scatter over
    the same polygon reads as confetti, and a north-south grid reads as a
    coincidence.

    Returns at most as many points as the footprint has room for — a
    multi-storey holds more cars than its footprint can show, and the caller
    records that as "one symbol stands for N cars" rather than overlapping them.
    """
    if count <= 0 or not rings_xy:
        return []
    outer = list(rings_xy[0] or [])
    holes = [list(r or []) for r in rings_xy[1:]]
    if len(outer) < 3:
        return []
    spacing = max(1.0, float(spacing_m))

    bearing = longest_edge_bearing(outer)
    cos_b, sin_b = math.cos(bearing), math.sin(bearing)

    # Into the lot's own frame, where its long side runs along the x axis.
    rot = [(x * cos_b + y * sin_b, -x * sin_b + y * cos_b) for x, y in outer]
    min_x = min(p[0] for p in rot)
    max_x = max(p[0] for p in rot)
    min_y = min(p[1] for p in rot)
    max_y = max(p[1] for p in rot)

    candidates: list[tuple[float, float]] = []
    cols = int((max_x - min_x) // spacing) + 1
    rows = int((max_y - min_y) // spacing) + 1
    # A pathological ring (a hairline sliver kilometres long) could otherwise
    # ask for an unbounded grid; cap the work at a generous multiple of what a
    # sane lot needs.
    budget = max(4 * count, 4096)
    for row in range(rows):
        for col in range(cols):
            if len(candidates) >= budget:
                break
            cx = min_x + (col + 0.5) * spacing
            cy = min_y + (row + 0.5) * spacing
            # Back out of the lot's frame into projected metres.
            x = cx * cos_b - cy * sin_b
            y = cx * sin_b + cy * cos_b
            if not point_in_ring(x, y, outer):
                continue
            if any(point_in_ring(x, y, h) for h in holes):
                continue
            candidates.append((x, y))

    if len(candidates) <= count:
        return candidates
    rng.shuffle(candidates)
    return candidates[:count]


# ─── Collecting the places cars are parked ───────────────────────────────────


@dataclass
class ParkingPlace:
    """One geometry that holds cars, with the estimate attached to it."""

    key: str
    geometry: dict
    estimate: ParkingEstimate
    origin: str  # kerb | lot
    name: str = ""
    access_class: str = "unknown"
    side: str = "unknown"
    orientation: str = "parallel"
    parking_form: str | None = None
    length_m: float | None = None
    area_m2: float | None = None


def _with_length(props: dict, geometry: dict) -> dict:
    """Ensure ``length_m`` is present, measuring the geometry when it is not.

    The street-space layers normalise a length; the plain ``streets`` layer does
    not, because nothing needed one there before. Measuring it here rather than
    demanding a particular layer keeps the modelled kerb working off whichever
    street network a workspace happens to have synced.
    """
    if props.get("length_m") is not None:
        return props
    measured = line_length_m(geometry)
    if measured is None:
        return props
    return {**props, "length_m": measured}


def _feature_key(props: dict, origin: str, index: int) -> str:
    osm_id = props.get("osm_id")
    if osm_id is None:
        return f"{origin}:idx:{index}"
    return f"{origin}:{props.get('osm_type') or 'way'}:{osm_id}"


def collect_places(
    *,
    kerb_features=None,
    lot_features=None,
    street_features=None,
    params=None,
    street_params=None,
    include=BASES,
    access=None,
) -> list[ParkingPlace]:
    """Turn the three input layers into the places that hold cars.

    Surveyed kerbs win over modelled ones on the same way: where OpenStreetMap
    has been surveyed — including a surveyed ``parking=no`` — the survey stands
    and no modelled cars are added on top of it.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS
    include = set(include or BASES)
    places: list[ParkingPlace] = []
    surveyed_ids: set = set()

    for i, feat in enumerate(kerb_features or []):
        geom = feat.get("geometry") or {}
        props = _with_length(feat.get("properties") or {}, geom)
        osm_id = props.get("osm_id")
        if osm_id is not None:
            surveyed_ids.add(osm_id)
        est = estimate_kerb(props, params=p, street_params=sp)
        if est.basis not in include or not est.count:
            continue
        places.append(
            ParkingPlace(
                key=_feature_key(props, "kerb", i),
                geometry=geom,
                estimate=est,
                origin="kerb",
                name=props.get("name") or "",
                access_class="public",
                side=props.get("side") or "unknown",
                orientation=props.get("orientation") or "parallel",
                length_m=_to_float(props.get("length_m")),
            )
        )

    if "modelled" in include:
        try:
            modelled_sides = max(1, int(p.get("modelled_sides") or 1))
        except (TypeError, ValueError):
            modelled_sides = 1
        for i, feat in enumerate(street_features or []):
            props = feat.get("properties") or {}
            if props.get("osm_id") in surveyed_ids:
                continue
            props = _with_length(props, feat.get("geometry") or {})
            est = estimate_modelled_kerb(props, params=p, street_params=sp)
            if est.basis not in include or not est.count:
                continue
            places.append(
                ParkingPlace(
                    key=_feature_key(props, "kerb", i),
                    geometry=feat.get("geometry") or {},
                    estimate=est,
                    origin="kerb",
                    name=props.get("name") or "",
                    access_class="public",
                    side="both" if modelled_sides >= 2 else "unknown",
                    orientation=p.get("modelled_orientation") or "parallel",
                    length_m=_to_float(props.get("length_m")),
                )
            )

    allowed_access = set(access) if access else None
    for i, feat in enumerate(lot_features or []):
        props = feat.get("properties") or {}
        access_class = props.get("access_class") or "unknown"
        if allowed_access is not None and access_class not in allowed_access:
            continue
        est = estimate_lot(props, params=p)
        if est.basis not in include or not est.count:
            continue
        places.append(
            ParkingPlace(
                key=_feature_key(props, "lot", i),
                geometry=feat.get("geometry") or {},
                estimate=est,
                origin="lot",
                name=props.get("name") or "",
                access_class=access_class,
                parking_form=props.get("parking_form"),
                area_m2=_to_float(props.get("area_m2")),
            )
        )

    # A stable order, so the thinning below and the seeded scatter produce the
    # same map on every request regardless of database row order.
    places.sort(key=lambda pl: pl.key)
    return places


def _totals(places) -> dict:
    totals = {"surveyed": 0, "modelled": 0, "total": 0, "kerb": 0, "lot": 0}
    for pl in places:
        n = pl.estimate.count or 0
        totals[pl.estimate.basis] = totals.get(pl.estimate.basis, 0) + n
        totals[pl.origin] = totals.get(pl.origin, 0) + n
        totals["total"] += n
    return totals


def _rings_xy(geometry: dict, forward) -> list[list[list]]:
    """Projected rings of a Polygon, or of every part of a MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [[_ring_xy(r, forward) for r in coords]] if coords else []
    if gtype == "MultiPolygon":
        return [[_ring_xy(r, forward) for r in poly] for poly in coords if poly]
    return []


def _lines_xy(geometry: dict, forward) -> list[list[tuple[float, float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "LineString":
        return [_ring_xy(coords, forward)]
    if gtype == "MultiLineString":
        return [_ring_xy(part, forward) for part in coords]
    return []


def build_parked_cars(
    *,
    center_lonlat,
    kerb_features=None,
    lot_features=None,
    street_features=None,
    params=None,
    street_params=None,
    include=BASES,
    access=None,
    max_symbols: int = MAX_SYMBOLS,
) -> dict:
    """A ``FeatureCollection`` of individual parked cars.

    Each point carries the ``basis`` it was drawn from and a ``represents``
    count. ``represents`` is normally 1; it rises when the output had to be
    thinned to stay drawable, or when a multi-storey holds more cars than its
    footprint can show. Wherever it is above 1, the legend has to say so.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS
    places = collect_places(
        kerb_features=kerb_features,
        lot_features=lot_features,
        street_features=street_features,
        params=p,
        street_params=sp,
        include=include,
        access=access,
    )
    totals = _totals(places)

    forward = make_projector(center_lonlat)
    inverse = make_inverse_projector(center_lonlat)

    thinning = 1
    if max_symbols and totals["total"] > max_symbols:
        thinning = math.ceil(totals["total"] / max_symbols)

    offset = _to_float(p.get("kerb_offset_m")) or 0.0
    jitter = _to_float(p.get("jitter_m")) or 0.0
    per_space_map = p.get("lot_area_per_space_m2") or {}

    features: list[dict] = []
    # A running remainder, so thinning keeps the total honest instead of
    # rounding every small street up to one car or down to none.
    carry = 0.0
    for place in places:
        count = place.estimate.count or 0
        if count <= 0:
            continue
        carry += count / thinning
        target = int(carry)
        carry -= target
        if target <= 0:
            continue

        rng = seeded_random(place.key)
        points: list[tuple[float, float]] = []
        if place.origin == "lot":
            parts = _rings_xy(place.geometry, forward)
            if not parts:
                continue
            form = place.parking_form or "default"
            per_space = (
                _to_float(per_space_map.get(form))
                or _to_float(per_space_map.get("default"))
                or 25.0
            )
            spacing = math.sqrt(per_space)
            # Split the target between the parts of a multipolygon in
            # proportion to their footprints.
            areas = [polygon_area_m2(part[0]) if part else 0.0 for part in parts]
            total_area = sum(areas) or 1.0
            for part, area in zip(parts, areas):
                share = int(round(target * area / total_area))
                if share <= 0:
                    continue
                points.extend(
                    scatter_in_polygon(part, share, spacing_m=spacing, rng=rng)
                )
        else:
            lines = _lines_xy(place.geometry, forward)
            if not lines:
                continue
            lengths = [
                sum(
                    math.hypot(b[0] - a[0], b[1] - a[1])
                    for a, b in zip(line, line[1:])
                )
                for line in lines
            ]
            total_len = sum(lengths) or 1.0
            for line, length in zip(lines, lengths):
                share = int(round(target * length / total_len))
                if share <= 0:
                    continue
                points.extend(
                    scatter_along_line(
                        line,
                        share,
                        side=place.side,
                        offset_m=offset,
                        jitter_m=jitter,
                        rng=rng,
                    )
                )

        if not points:
            continue
        represents = max(1, int(round(count / len(points))))
        for x, y in points:
            lon, lat = inverse(x, y)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                    "properties": {
                        "basis": place.estimate.basis,
                        "origin": place.origin,
                        "represents": represents,
                        "method": place.estimate.method,
                        "confidence": place.estimate.confidence,
                        "access_class": place.access_class,
                        "name": place.name,
                    },
                }
            )

    return {
        "type": "FeatureCollection",
        "features": features,
        "counts": totals,
        "symbols": len(features),
        "represents": thinning,
        "truncated": thinning > 1,
        "occupancy_rate": _to_float(p.get("occupancy_rate")) or 1.0,
        "needs_review": bool(p.get("needs_review")),
        "source": p.get("source"),
    }


def build_parking_density(
    *,
    kerb_features=None,
    lot_features=None,
    street_features=None,
    params=None,
    street_params=None,
    include=BASES,
    access=None,
) -> dict:
    """The same estimates, kept on their own geometry instead of scattered.

    This is what the map draws when it is zoomed too far out for individual
    symbols to mean anything. Re-using the source geometry is both cheaper than
    scattering and truer than re-binning it into an arbitrary grid: a kerb keeps
    its street and a car park keeps its footprint.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS
    places = collect_places(
        kerb_features=kerb_features,
        lot_features=lot_features,
        street_features=street_features,
        params=p,
        street_params=sp,
        include=include,
        access=access,
    )

    features = []
    for place in places:
        count = place.estimate.count or 0
        if count <= 0:
            continue
        props = {
            "cars": count,
            "basis": place.estimate.basis,
            "origin": place.origin,
            "method": place.estimate.method,
            "confidence": place.estimate.confidence,
            "access_class": place.access_class,
            "name": place.name,
            "cars_per_100m": None,
            "cars_per_1000m2": None,
        }
        if place.origin == "kerb" and place.length_m:
            props["cars_per_100m"] = round(count * 100.0 / place.length_m, 1)
        if place.origin == "lot" and place.area_m2:
            props["cars_per_1000m2"] = round(count * 1000.0 / place.area_m2, 1)
        features.append(
            {"type": "Feature", "geometry": place.geometry, "properties": props}
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "counts": _totals(places),
        "occupancy_rate": _to_float(p.get("occupancy_rate")) or 1.0,
        "needs_review": bool(p.get("needs_review")),
        "source": p.get("source"),
    }
