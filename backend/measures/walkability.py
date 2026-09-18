"""Walkability — how good is this street for someone on foot, and how sure are we?

The parked-car layer shows where a city stores its cars. This module is the
other half of that argument: what walking is actually like on the same streets.
Each street gets a *class* — comfortable, usable, tight, hostile, or "not enough
data" — from two components, ``safety`` (how exposed a person on foot is to
motor traffic) and ``comfort`` (whether the walk is pleasant and possible at
all).

Three rules govern everything here, and none may be relaxed:

1. **Silence is never a middling score.** A factor the data cannot speak to
   returns ``None`` and is dropped from the weighted mean, not scored 0.5.
   Substituting a neutral value would quietly turn "nobody has surveyed this"
   into "it is average", which is the failure this whole feature exists to
   avoid. Every dropped factor is named in ``unknowns`` so a reader can see
   exactly what the class does *not* rest on.
2. **Below ``min_coverage`` there is no class.** A street whose known weight
   falls under the threshold is reported as ``unknown``, not as a number
   computed from a handful of inputs. The map draws it, faintly, and says so.
3. **Evidence outranks proximity.** A street surveyed as having no pavement is
   never rescued by a footway line drawn nearby. The proximity join runs only
   where the street either says ``sidewalk=separate`` — an explicit pointer to
   a pavement mapped as its own way — or says nothing at all.

The 0–100 numbers are in the output because CLAUDE.md principle 3 requires the
calculation to be auditable. They are *not* for the map: banded inputs cannot
support a printed score, so the UI speaks in words and keeps the numbers behind
an opt-in.

Pure module: no Django, no I/O, no database. GeoJSON in, GeoJSON out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from measures import street_space
from measures.geo import (
    SegmentGrid,
    iter_linestrings,
    line_length_m,
    make_projector,
)

# ─── Parameters ──────────────────────────────────────────────────────────────
# Defaults, not truths. A municipality that weighs these differently — or whose
# design standard states different widths — overrides any of them via
# ``Workspace.settings["walkability"]``. Nothing here may be hard-wired to one
# country's guidance or one city's street layout.
#
# The two weight groups are flat top-level keys rather than one nested
# ``weights`` dict on purpose: ``params_for`` merges one level deep, so this way
# a workspace can raise a single factor without restating the other four.
DEFAULT_PARAMS: dict[str, Any] = {
    # How exposed a person on foot is to motor traffic.
    "weights_safety": {
        "footway_separation": 0.30,
        "traffic_speed": 0.30,
        "lane_count": 0.15,
        "crossings": 0.15,
        "obstacles": 0.10,
    },
    # Whether the walk is pleasant, and possible at all.
    "weights_comfort": {
        "footway_width": 0.35,
        "kerb_parking": 0.20,
        "step_free": 0.20,
        "surface": 0.15,
        "lit": 0.10,
    },
    # Safety leads because being hit by a car is not commensurable with an
    # unpleasant surface, but comfort is not a rounding error: a pavement too
    # narrow to pass someone on is a pavement people step off.
    "headline_weights": {"safety": 0.6, "comfort": 0.4},
    # Thresholds on the 0–100 score. Anything below `tight` is hostile.
    "class_thresholds": {"comfortable": 70, "usable": 50, "tight": 30},
    # Below this share of known weight, no class is reported at all.
    "min_coverage": 0.5,
    # Pavement widths. Two people passing need about 1.8 m; a wheelchair and a
    # pushchair need more. Below `minimum_width_m` a pavement is nominal.
    "comfortable_width_m": 2.5,
    "minimum_width_m": 1.5,
    # Join radii.
    "snap_m": 25.0,
    "crossing_snap_m": 40.0,
    # One safe crossing every 150 m of street. A street shorter than this is not
    # penalised for having none.
    "crossing_target_spacing_m": 150.0,
    # Speed banding. 30 km/h is the threshold below which a collision is usually
    # survivable; above `speed_hostile_kmh` walking alongside is unpleasant at
    # best whatever else is true.
    "speed_comfort_kmh": 30.0,
    "speed_hostile_kmh": 70.0,
    # What an implicit national speed zone (`maxspeed=DE:urban`, `NZ:rural`, …)
    # is worth in km/h. Deliberately EMPTY: what "urban" means is a question of
    # national law, and a table of country defaults in core code is exactly the
    # coupling CLAUDE.md principle 1 forbids. An un-configured workspace
    # honestly reports the speed as unknown instead of assuming somebody's
    # highway code. Supply the local numbers per workspace, keyed by the zone
    # string exactly as OpenStreetMap writes it, e.g. {"de:urban": 50}.
    "implicit_maxspeed_kmh": {},
    # Walking quality by surface, and by the `smoothness` tag where it exists.
    "surface_quality": {
        "asphalt": 1.0,
        "concrete": 1.0,
        "paving_stones": 1.0,
        "concrete:plates": 0.9,
        "chipseal": 0.9,
        "wood": 0.7,
        "compacted": 0.7,
        "fine_gravel": 0.6,
        "sett": 0.4,
        "cobblestone": 0.4,
        "unhewn_cobblestone": 0.2,
        "gravel": 0.2,
        "ground": 0.2,
        "dirt": 0.2,
        "earth": 0.2,
        "grass": 0.2,
        "sand": 0.1,
        "mud": 0.0,
    },
    "smoothness_quality": {
        "excellent": 1.0,
        "good": 0.9,
        "intermediate": 0.7,
        "bad": 0.4,
        "very_bad": 0.25,
        "horrible": 0.1,
        "very_horrible": 0.05,
        "impassable": 0.0,
    },
    "source": {
        "title": "OpenMobility OS default walkability parameters",
        "note": (
            "Generic defaults for scoring a street from the pedestrian data "
            "OpenStreetMap carries. Replace with the walking-design standard "
            "that applies in your jurisdiction via "
            "Workspace.settings['walkability']."
        ),
    },
    # Marked for review in the same spirit as measures/effects.py: these are
    # plausible planning figures, not values a maintainer has checked against a
    # named standard. The UI surfaces the flag so no reader mistakes one for
    # the other.
    "needs_review": True,
}

# Every class the scorer can assign, worst first, with `unknown` kept apart from
# the ranked ones because it is not a degree of anything.
WALK_CLASSES = ("hostile", "tight", "usable", "comfortable")
UNKNOWN_CLASS = "unknown"

# The words the popup uses for a component score. Bands, not numbers.
BANDS = ("poor", "fair", "good")

MODES = ("classes", "space_split")

# Kerbside parking layouts, and what each one does to the person walking past.
# `on_kerb` is the hinge to the parked-car layer: it reads the very same
# `parking_type` that layer draws its symbols from.
KERB_PARKING_QUALITY = {
    "on_kerb": 0.0,
    "half_on_kerb": 0.3,
    "painted_area_only": 0.7,
    "shoulder": 0.8,
    "street_side": 1.0,
    "lane": 1.0,
}


def params_for(workspace=None) -> dict[str, Any]:
    """Merge ``Workspace.settings["walkability"]`` over the defaults."""
    overrides = {}
    if workspace is not None:
        overrides = (getattr(workspace, "settings", None) or {}).get("walkability") or {}
    merged = dict(DEFAULT_PARAMS)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


# ─── One factor's verdict ────────────────────────────────────────────────────


@dataclass
class Factor:
    """What one input says about a street, and how it came to say it.

    ``value`` of ``None`` means the data does not speak to this factor. It is
    emphatically not 0, and it is not 0.5 either: the compositor drops it and
    records its name, so a low coverage stays visible instead of being averaged
    away into a confident-looking middle.
    """

    value: float | None
    method: str
    inputs: dict = field(default_factory=dict)
    confidence: str = "low"

    def as_dict(self) -> dict:
        return {
            "value": None if self.value is None else round(self.value, 3),
            "method": self.method,
            "inputs": self.inputs,
            "confidence": self.confidence,
        }


UNKNOWN_FACTOR_METHODS = {
    "no_footway_record",
    "layer_absent",
    "silent",
}


# ─── The ten factors ─────────────────────────────────────────────────────────
# Each is a pure (street_props, context) -> Factor. The context carries the
# joins: the footway record matched to this street, the crossings and obstacles
# found on it, the kerbside-parking record, and the parameters.


def _f_footway_separation(street: dict, ctx: dict) -> Factor:
    """Is the person on foot separated from the traffic at all?"""
    foot = ctx.get("footway")
    shared = bool(
        (foot or {}).get("shared_space")
        or str(street.get("highway") or "").lower() in ("pedestrian", "living_street")
    )
    if shared:
        # A shared space has no pavement by design, and needing one would be a
        # category error. Not a full 1.0: the arrangement depends on drivers
        # yielding, which not every shared space achieves.
        return Factor(0.9, "shared_space", {"highway": street.get("highway")}, "medium")
    if foot is None:
        return Factor(None, "no_footway_record", {}, "low")

    present = foot.get("footway_present")
    sides = foot.get("sides")
    if present is True:
        if foot.get("foot_scheme") == "separate_way":
            # A pavement mapped as its own way is one line beside the street.
            # Its `sides` reads "both" only in the sense that the way itself is
            # walkable end to end — it says nothing about the other kerb, and
            # crediting this street with two pavements would be inventing one.
            return Factor(0.8, "separate_way_matched", {"sides": sides}, "medium")
        both = sides == "both"
        return Factor(
            1.0 if both else 0.8,
            "footway_both_sides" if both else "footway_one_side",
            {"sides": sides},
            "high",
        )
    if present is False:
        return Factor(0.0, "surveyed_no_footway", {"sides": sides}, "high")
    return Factor(None, "silent", {"sides": sides}, "low")


def _f_traffic_speed(street: dict, ctx: dict) -> Factor:
    """How fast the motor traffic beside the pavement is allowed to go."""
    p = ctx["params"]
    source = street.get("maxspeed_source")
    kmh = _to_float(street.get("maxspeed_kmh"))
    method = "tagged"
    confidence = "high"

    if source == "unlimited":
        # An unrestricted road is a survey result, not a gap: score it as the
        # worst case. Treating it as 0 km/h would rank an autobahn as the
        # calmest street in town.
        return Factor(0.0, "unlimited", {"maxspeed_raw": street.get("maxspeed_raw")}, "high")

    if kmh is None and source == "implicit":
        zone = str(street.get("maxspeed_zone") or "").lower()
        table = p.get("implicit_maxspeed_kmh") or {}
        resolved = _to_float(table.get(zone))
        if resolved is None:
            # The workspace has not said what this zone means locally, and this
            # module will not guess on a country's behalf.
            return Factor(None, "implicit_zone_unresolved", {"zone": zone}, "low")
        kmh = resolved
        method = "implicit_zone_resolved"
        confidence = "medium"

    if kmh is None:
        return Factor(
            None,
            "unparsed" if source == "unparsed" else "unknown",
            {"maxspeed_raw": street.get("maxspeed_raw")},
            "low",
        )

    comfort = _to_float(p.get("speed_comfort_kmh")) or 30.0
    hostile = _to_float(p.get("speed_hostile_kmh")) or 70.0
    return Factor(
        _ramp_down(kmh, comfort, hostile),
        method,
        {"maxspeed_kmh": kmh},
        confidence,
    )


def _f_lane_count(street: dict, ctx: dict) -> Factor:
    """How much carriageway there is to cross, and to walk beside."""
    lanes = _to_int(street.get("lanes"))
    if lanes is None or lanes <= 0:
        return Factor(None, "unknown", {}, "low")
    if lanes <= 2:
        value = 1.0
    elif lanes == 3:
        value = 0.6
    elif lanes == 4:
        value = 0.3
    else:
        value = 0.0
    return Factor(value, "lane_count", {"lanes": lanes}, "high")


def _f_crossings(street: dict, ctx: dict) -> Factor:
    """Can someone on foot get across, and how far must they walk to do it?"""
    p = ctx["params"]
    if not ctx.get("crossing_layer_present"):
        # No crossings layer synced. That is not "there are no crossings" — it
        # is "nobody has told us", and scoring it 0 would condemn every
        # workspace that has not got round to syncing the layer.
        return Factor(None, "layer_absent", {}, "low")

    length = _to_float(street.get("length_m"))
    if length is None or length <= 0:
        return Factor(None, "length_unknown", {}, "low")

    target = _to_float(p.get("crossing_target_spacing_m")) or 150.0
    found = ctx.get("crossings") or []
    count = len(found)

    if count == 0:
        if length < target:
            # Too short to need one of its own. Saying otherwise would mark
            # every side street in a well-crossed city hostile.
            return Factor(
                1.0,
                "shorter_than_target_spacing",
                {"length_m": length, "target_spacing_m": target},
                "medium",
            )
        return Factor(0.0, "no_crossing_found", {"length_m": length}, "medium")

    value = min(1.0, count * target / length)
    # A crossing with signals or an island is worth more than a painted line,
    # but the painted line still counts: this nudges rather than re-ranks.
    protected = sum(
        1
        for c in found
        if c.get("has_signals") is True
        or c.get("island") is True
        or c.get("crossing_kind") in ("traffic_signals", "island")
    )
    if protected:
        value = min(1.0, value + 0.1 * protected / count)
    return Factor(
        value,
        "crossing_spacing",
        {"count": count, "protected": protected, "length_m": length},
        "medium",
    )


def _f_obstacles(street: dict, ctx: dict) -> Factor:
    """Things recorded as standing in a walking route's way."""
    if not ctx.get("obstacle_layer_present"):
        return Factor(None, "layer_absent", {}, "low")
    found = ctx.get("obstacles") or []
    if not found:
        # The layer is synced and nothing matched this street. That is a real
        # reading, but a weak one: the obstacle list is knowingly incomplete
        # (see docs/AREA_TARGETS.md), so it never claims high confidence.
        return Factor(1.0, "no_obstacle_matched", {}, "low")
    kinds = sorted({str(o.get("obstacle_type") or "unknown") for o in found})
    return Factor(
        max(0.0, 1.0 - 0.5 * len(found)),
        "obstacles_matched",
        {"count": len(found), "kinds": kinds},
        "medium",
    )


def _f_footway_width(street: dict, ctx: dict) -> Factor:
    """How wide the pavement is — tagged widths only, never an estimate."""
    foot = ctx.get("footway")
    if not foot:
        return Factor(None, "no_footway_record", {}, "low")
    if foot.get("width_source") != "tagged":
        # A pavement width is the one number this feature must not invent.
        # There is no lane count to derive it from, and a guessed width would
        # drive the single heaviest comfort weight.
        return Factor(None, "width_not_tagged", {}, "low")
    width = _to_float(foot.get("width_m"))
    if width is None or width <= 0:
        return Factor(None, "width_not_tagged", {}, "low")
    p = ctx["params"]
    minimum = _to_float(p.get("minimum_width_m")) or 1.5
    comfortable = _to_float(p.get("comfortable_width_m")) or 2.5
    return Factor(
        _ramp_up(width, minimum, comfortable),
        "tagged_width",
        {"width_m": width},
        "high",
    )


def _f_kerb_parking(street: dict, ctx: dict) -> Factor:
    """Do the parked cars stand on the carriageway, or on the pavement?

    This is the hinge between the two halves of the Parking vs Walking view: it
    reads the very same ``parking_type`` the parked-car layer draws from, so a
    street whose comfort is dragged down here is visibly the street just filled
    with car symbols.
    """
    parking = ctx.get("parking")
    if parking is None:
        return Factor(None, "silent", {}, "low")
    if parking.get("parking_present") is False:
        return Factor(1.0, "surveyed_no_parking", {}, "high")
    ptype = str(parking.get("parking_type") or "").lower()
    if ptype not in KERB_PARKING_QUALITY:
        return Factor(None, "unrecognised_parking_type", {"parking_type": ptype}, "low")
    return Factor(
        KERB_PARKING_QUALITY[ptype],
        "parking_type",
        {"parking_type": ptype},
        "high",
    )


def _f_step_free(street: dict, ctx: dict) -> Factor:
    """Can someone using a wheelchair, or pushing a pram, actually get along here?"""
    foot = ctx.get("footway") or {}
    parts: list[tuple[float, str]] = []

    if foot.get("is_steps"):
        # Steps are decisive. Nothing else on the street redeems them.
        return Factor(
            0.0,
            "steps",
            {"step_count": foot.get("step_count")},
            "high",
        )

    incline = _to_float(foot.get("incline_pct"))
    if incline is not None:
        steep = abs(incline)
        if steep >= 8:
            parts.append((0.2, "incline"))
        elif steep >= 6:
            parts.append((0.5, "incline"))
        else:
            parts.append((1.0, "incline"))

    kerbs = [str(c.get("kerb")) for c in (ctx.get("crossings") or []) if c.get("kerb")]
    if kerbs:
        lowered = all(k in ("flush", "lowered") for k in kerbs)
        parts.append((1.0 if lowered else 0.3, "crossing_kerb"))

    if not parts:
        return Factor(None, "silent", {}, "low")
    # The binding constraint, not the average: one raised kerb stops a wheelchair
    # however gentle the gradient either side of it.
    value, method = min(parts, key=lambda pair: pair[0])
    return Factor(
        value,
        method,
        {"incline_pct": incline, "kerbs": sorted(set(kerbs)) or None},
        "medium",
    )


def _f_surface(street: dict, ctx: dict) -> Factor:
    """What the pavement is made of. `smoothness` wins where it is tagged."""
    foot = ctx.get("footway") or {}
    p = ctx["params"]
    smoothness = str(foot.get("smoothness") or "").lower()
    table = p.get("smoothness_quality") or {}
    if smoothness in table:
        # `smoothness` describes the condition the surface is actually in, which
        # outranks what it is nominally made of: worn asphalt is not asphalt.
        return Factor(
            float(table[smoothness]), "smoothness", {"smoothness": smoothness}, "high"
        )
    surface = str(foot.get("surface") or "").lower()
    quality = (p.get("surface_quality") or {}).get(surface)
    if quality is None:
        return Factor(None, "silent", {"surface": surface or None}, "low")
    return Factor(float(quality), "surface", {"surface": surface}, "medium")


def _f_lit(street: dict, ctx: dict) -> Factor:
    """Street lighting — three-state, because unlit and unsurveyed differ."""
    foot = ctx.get("footway") or {}
    lit = foot.get("lit")
    if lit is True:
        return Factor(1.0, "lit", {}, "high")
    if lit is False:
        return Factor(0.0, "surveyed_unlit", {}, "high")
    return Factor(None, "silent", {}, "low")


SAFETY_FACTORS = {
    "footway_separation": _f_footway_separation,
    "traffic_speed": _f_traffic_speed,
    "lane_count": _f_lane_count,
    "crossings": _f_crossings,
    "obstacles": _f_obstacles,
}

COMFORT_FACTORS = {
    "footway_width": _f_footway_width,
    "kerb_parking": _f_kerb_parking,
    "step_free": _f_step_free,
    "surface": _f_surface,
    "lit": _f_lit,
}

ALL_FACTORS = {**SAFETY_FACTORS, **COMFORT_FACTORS}


# ─── Composition ─────────────────────────────────────────────────────────────


def compose(factors: dict, weights: dict, min_coverage: float) -> tuple:
    """Weighted mean over the factors that had something to say.

    Returns ``(score_0_100_or_None, coverage, unknowns)``. A ``None`` factor is
    dropped from both the numerator and the denominator — never scored as a
    middling 0.5 — and its name goes into ``unknowns``. Below ``min_coverage``
    the score is withheld entirely rather than computed from the remainder.

    The arithmetic deliberately mirrors ``scoring.compute_priority_score``,
    including its zero-total guard, so a walking score means the same kind of
    thing a measure's priority score does.
    """
    total_w = 0.0
    known_w = 0.0
    acc = 0.0
    unknowns: list[str] = []
    for name, weight in weights.items():
        w = float(weight)
        if w <= 0:
            continue
        total_w += w
        factor = factors.get(name)
        if factor is None or factor.value is None:
            unknowns.append(name)
            continue
        known_w += w
        acc += float(factor.value) * w
    if total_w <= 0:
        return None, 0.0, unknowns
    coverage = known_w / total_w
    if known_w <= 0 or coverage < min_coverage:
        return None, coverage, unknowns
    return round(100.0 * acc / known_w, 1), coverage, unknowns


def classify(score: float | None, thresholds: dict) -> str:
    """Turn a 0–100 score into one of the named classes."""
    if score is None:
        return UNKNOWN_CLASS
    if score >= float(thresholds.get("comfortable", 70)):
        return "comfortable"
    if score >= float(thresholds.get("usable", 50)):
        return "usable"
    if score >= float(thresholds.get("tight", 30)):
        return "tight"
    return "hostile"


def band(score: float | None, thresholds: dict) -> str:
    """Turn a component score into a word, for the popup."""
    if score is None:
        return UNKNOWN_CLASS
    if score >= float(thresholds.get("comfortable", 70)):
        return "good"
    if score >= float(thresholds.get("usable", 50)):
        return "fair"
    return "poor"


def _confidence_for(coverage: float, footway_match: str, walk_class: str) -> str:
    if walk_class == UNKNOWN_CLASS:
        return "low"
    if coverage >= 0.8:
        level = "high"
    elif coverage >= 0.6:
        level = "medium"
    else:
        level = "low"
    if footway_match == "proximity" and level == "high":
        # A pavement matched by nearness rather than by id might belong to the
        # parallel street. The map shows that as reduced opacity.
        level = "medium"
    return level


# ─── The join ────────────────────────────────────────────────────────────────


def _props(feature) -> dict:
    return (feature or {}).get("properties") or {}


def _osm_key(props: dict):
    osm_id = props.get("osm_id")
    return None if osm_id in (None, "") else str(osm_id)


def _index_by_osm_id(features) -> dict:
    out: dict[str, dict] = {}
    for feat in features or []:
        props = _props(feat)
        key = _osm_key(props)
        if key is not None:
            out.setdefault(key, props)
    return out


def _group_by_osm_id(features) -> dict:
    out: dict[str, list] = {}
    for feat in features or []:
        props = _props(feat)
        key = _osm_key(props)
        if key is not None:
            out.setdefault(key, []).append(props)
    return out


def _point_xy(geometry, transform):
    if not geometry or geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates") or []
    if len(coords) < 2:
        return None
    return transform(coords[0], coords[1])


def _project_lines(geometry, transform) -> list:
    lines = []
    for line in iter_linestrings(geometry):
        pts = [transform(c[0], c[1]) for c in line if len(c) >= 2]
        if len(pts) >= 2:
            lines.append(pts)
    return lines


def _match_footways(streets_xy, footways_xy, by_osm_id, snap_m):
    """Attach a footway record to each street: by id first, by nearness second.

    Returns a list of ``(props_or_None, match_kind)`` parallel to the streets.

    The proximity pass runs **only** where the street's own record says
    ``sidewalk=separate`` — an explicit pointer to a pavement mapped as its own
    way — or where there is no record at all. A street surveyed as having no
    pavement keeps that answer: evidence outranks a line that happens to run
    nearby. Without the pass at all, the separate-way scheme would be unusable,
    which would blank out precisely the cities that map pedestrian space best.
    """
    results: list[tuple[dict | None, str]] = []
    separate_ways: list[dict] = []
    grid = SegmentGrid(snap_m)
    needs_grid = False

    for street_props, _lines in streets_xy:
        key = _osm_key(street_props)
        record = by_osm_id.get(key) if key is not None else None
        if record is not None and record.get("sides") != "separate":
            results.append((record, "osm_id"))
        else:
            results.append((record, "pending"))
            needs_grid = True

    if not needs_grid:
        return [(record, "osm_id") for record, _state in results]

    # The footways arrive already projected, so the index costs one pass.
    for props, pts in footways_xy:
        if props.get("foot_scheme") != "separate_way":
            continue
        ref = len(separate_ways)
        if grid.add_line(ref, pts):
            separate_ways.append(props)

    out: list[tuple[dict | None, str]] = []
    for index, (record, state) in enumerate(results):
        if state == "osm_id":
            out.append((record, "osm_id"))
            continue
        best_props = None
        best_dist = float("inf")
        if separate_ways:
            for point in _sample_points(streets_xy[index][1]):
                ref, dist = grid.nearest(point[0], point[1])
                if ref is not None and dist <= snap_m and dist < best_dist:
                    best_dist = dist
                    best_props = separate_ways[ref]
        if best_props is not None:
            out.append((best_props, "proximity"))
        elif record is not None:
            # The street pointed at a separate pavement and we could not find
            # it. Keep the pointer record — it still carries the street's own
            # surface and lighting tags — but say the match failed.
            out.append((record, "none"))
        else:
            out.append((None, "none"))
    return out


def _sample_points(lines, limit: int = 12):
    """A handful of points along a street, for querying the footway index.

    Querying every vertex of a long way would be wasteful and querying only the
    midpoint would miss a pavement that runs beside one end. A bounded, evenly
    spread sample is enough to decide whether *a* pavement runs alongside.
    """
    points = [pt for line in lines for pt in line]
    if not points:
        return []
    if len(points) <= limit:
        return points
    step = len(points) / float(limit)
    return [points[min(len(points) - 1, int(i * step))] for i in range(limit)]


# ─── Space split ─────────────────────────────────────────────────────────────


def space_split(footway: dict | None, parking: dict | None, *, street_params) -> tuple:
    """How this street's width divides between people on foot and parked cars.

    Returns ``(footway_width_total_m, parking_width_m, space_balance)``, where
    ``space_balance`` runs from −1 (all of the measurable space goes to parked
    cars) through 0 to +1 (all of it to people on foot). Diverging, because
    "who gets the space?" has a meaningful midpoint in a way a walking score
    does not.

    Every part is ``None`` unless both sides are actually known. Tagged footway
    widths are rare, so this will be ``None`` on most streets in most cities —
    which is why the collection reports its own coverage for this mode rather
    than letting a sparse layer look like a complete one.
    """
    foot_total = None
    if footway and footway.get("width_source") == "tagged":
        width = _to_float(footway.get("width_m"))
        if width is not None and width > 0:
            # Only the street-tag scheme can say there are two pavements. A
            # separately-mapped way is one line, and doubling its width would
            # credit the street with a pavement nobody has mapped.
            two_sides = (
                footway.get("sides") == "both"
                and footway.get("foot_scheme") != "separate_way"
            )
            foot_total = round(width * (2 if two_sides else 1), 2)

    park_total = None
    if parking is not None:
        if parking.get("parking_present") is False:
            park_total = 0.0
        elif parking.get("parking_present") is True:
            orientation = parking.get("orientation") or "parallel"
            per_side = street_space.parking_width(orientation, params=street_params)
            sides = 2 if parking.get("side") == "both" else 1
            park_total = round(per_side * sides, 2)

    balance = None
    if foot_total is not None and park_total is not None:
        denominator = foot_total + park_total
        if denominator > 0:
            balance = round((foot_total - park_total) / denominator, 3)
    return foot_total, park_total, balance


# ─── The build ───────────────────────────────────────────────────────────────


def build_walkability(
    *,
    center_lonlat,
    street_features,
    footway_features=None,
    crossing_features=None,
    obstacle_features=None,
    parking_features=None,
    params=None,
    street_params=None,
    mode="classes",
    classes=None,
) -> dict:
    """Score every street for walking and return them as a FeatureCollection.

    Every input layer is optional. A workspace with nothing but a street network
    still gets a collection back — every street classed ``unknown``, with
    ``unknowns`` naming what is missing — because "we cannot say" is an answer
    the map is built to show, and an error would only hide the gap.

    Pass ``None`` for a layer the workspace has not synced and ``[]`` for one it
    has synced that happens to hold nothing: the crossings and obstacles factors
    read the two differently, because "nobody has looked" and "somebody looked
    and found none" are not the same claim.
    """
    p = params or DEFAULT_PARAMS
    sp = street_params or street_space.DEFAULT_PARAMS
    mode = mode if mode in MODES else "classes"
    wanted = set(classes) if classes else None

    transform = make_projector(center_lonlat)

    # Project the streets once; everything downstream reuses this.
    streets_xy: list[tuple[dict, list]] = []
    street_geoms: list[dict] = []
    for feat in street_features or []:
        geom = feat.get("geometry") or {}
        lines = _project_lines(geom, transform)
        streets_xy.append((_props(feat), lines))
        street_geoms.append(geom)

    footways_xy = [
        (_props(f), pt)
        for f in (footway_features or [])
        for pt in _project_lines(f.get("geometry") or {}, transform)
    ]
    # Only the street-tag scheme is keyed on a street's own id. A standalone
    # footway carries its own way id, which is not a street's, so indexing it
    # here would only invite a coincidental match.
    footway_by_id = _index_by_osm_id(
        [f for f in (footway_features or []) if _props(f).get("foot_scheme") == "street_tag"]
    )

    snap_m = _to_float(p.get("snap_m")) or 25.0
    matches = _match_footways(streets_xy, footways_xy, footway_by_id, snap_m)

    crossings_by_street = _snap_crossings(
        streets_xy, crossing_features, transform, _to_float(p.get("crossing_snap_m")) or 40.0
    )
    obstacles_by_id = _group_by_osm_id(
        [
            f
            for f in (obstacle_features or [])
            if str(_props(f).get("affects") or "") in ("walking", "both")
        ]
    )
    parking_by_id = _index_by_osm_id(parking_features)

    # `None` means the workspace has not synced this layer; an empty list means
    # it has, and the layer holds nothing here. The difference matters: the
    # first is silence and scores nothing, the second is a reading. Callers that
    # cannot tell the two apart should pass `None`.
    crossing_layer_present = crossing_features is not None
    obstacle_layer_present = obstacle_features is not None

    thresholds = p.get("class_thresholds") or {}
    min_coverage = _to_float(p.get("min_coverage"))
    min_coverage = 0.5 if min_coverage is None else min_coverage
    headline = p.get("headline_weights") or {"safety": 0.6, "comfort": 0.4}

    features: list[dict] = []
    counts = {name: 0 for name in (*WALK_CLASSES, UNKNOWN_CLASS)}
    coverage_sum = 0.0
    space_known = 0

    for index, (street_props, _lines) in enumerate(streets_xy):
        footway, footway_match = matches[index]
        key = _osm_key(street_props)
        length = _to_float(street_props.get("length_m"))
        if length is None:
            length = line_length_m(street_geoms[index])

        ctx = {
            "params": p,
            "footway": footway,
            "crossings": crossings_by_street.get(index) or [],
            "crossing_layer_present": crossing_layer_present,
            "obstacles": (obstacles_by_id.get(key) or []) if key is not None else [],
            "obstacle_layer_present": obstacle_layer_present,
            "parking": parking_by_id.get(key) if key is not None else None,
        }
        scored_street = {**street_props, "length_m": length}

        factors = {name: fn(scored_street, ctx) for name, fn in ALL_FACTORS.items()}
        safety, safety_cov, safety_unknown = compose(
            factors, p.get("weights_safety") or {}, min_coverage
        )
        comfort, comfort_cov, comfort_unknown = compose(
            factors, p.get("weights_comfort") or {}, min_coverage
        )

        w_safety = float(headline.get("safety", 0.6))
        w_comfort = float(headline.get("comfort", 0.4))
        total_headline = w_safety + w_comfort or 1.0
        coverage = round(
            (w_safety * safety_cov + w_comfort * comfort_cov) / total_headline, 3
        )

        # The headline drops a missing component exactly as `compose` drops a
        # missing factor: a street whose safety is well covered still gets a
        # class, and the popup says comfort is unknown.
        parts = [(safety, w_safety), (comfort, w_comfort)]
        known = [(v, w) for v, w in parts if v is not None]
        if not known or coverage < min_coverage:
            score = None
        else:
            score = round(
                sum(v * w for v, w in known) / sum(w for _v, w in known), 1
            )

        walk_class = classify(score, thresholds)
        confidence = _confidence_for(coverage, footway_match, walk_class)
        unknowns = safety_unknown + comfort_unknown

        foot_width, park_width, balance = space_split(
            footway, ctx["parking"], street_params=sp
        )
        if balance is not None:
            space_known += 1

        counts[walk_class] += 1
        coverage_sum += coverage

        if wanted is not None and walk_class not in wanted:
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": street_geoms[index],
                "properties": {
                    "name": _street_name(street_props),
                    "osm_id": street_props.get("osm_id"),
                    "highway": street_props.get("highway"),
                    "length_m": length,
                    "walk_class": walk_class,
                    "safety_band": band(safety, thresholds),
                    "comfort_band": band(comfort, thresholds),
                    "confidence": confidence,
                    "coverage": coverage,
                    "unknowns": unknowns,
                    "footway_match": footway_match,
                    "space_balance": balance,
                    "footway_width_total_m": foot_width,
                    "parking_width_m": park_width,
                    # The numbers. Present because principle 3 requires the
                    # calculation to be auditable; the map never draws them.
                    "score": score,
                    "safety": safety,
                    "comfort": comfort,
                    "factors": {
                        name: factor.as_dict() for name, factor in factors.items()
                    },
                },
            }
        )

    total = len(streets_xy)
    return {
        "type": "FeatureCollection",
        "features": features,
        "mode": mode,
        "counts": counts,
        "streets": total,
        "coverage": round(coverage_sum / total, 3) if total else 0.0,
        "space_split_coverage": round(space_known / total, 3) if total else 0.0,
        "layers_used": {
            "footways": footway_features is not None,
            "pedestrian_crossings": crossing_layer_present,
            "obstacles": obstacle_layer_present,
            "street_parking": parking_features is not None,
        },
        "method": "weighted_mean_of_known_factors",
        "class_thresholds": dict(thresholds),
        "params_used": {
            "weights_safety": dict(p.get("weights_safety") or {}),
            "weights_comfort": dict(p.get("weights_comfort") or {}),
            "headline_weights": dict(headline),
            "min_coverage": min_coverage,
            "snap_m": snap_m,
        },
        "needs_review": bool(p.get("needs_review")),
        "source": p.get("source"),
        "note": (
            "Classes are thresholds on an auditable 0-100 score. A factor the "
            "data cannot speak to is dropped from the mean and named in "
            "'unknowns'; it is never scored as a middling value. Streets below "
            "the coverage threshold are reported as 'unknown' rather than "
            "guessed at. A workspace with no footways layer therefore reports "
            "most streets as 'unknown' whatever their traffic: comfort is "
            "40 percent of the picture, and without it the coverage of even a "
            "well-surveyed street cannot reach the threshold. That is the "
            "honest reading, and the argument for syncing the layer."
        ),
    }


def _snap_crossings(streets_xy, crossing_features, transform, snap_m) -> dict:
    """Assign each crossing point to the nearest street within ``snap_m``."""
    if not crossing_features:
        return {}
    grid = SegmentGrid(snap_m)
    any_segment = False
    for index, (_props_, lines) in enumerate(streets_xy):
        for pts in lines:
            if grid.add_line(index, pts):
                any_segment = True
    if not any_segment:
        return {}

    out: dict[int, list] = {}
    for feat in crossing_features:
        xy = _point_xy(feat.get("geometry") or {}, transform)
        if xy is None:
            continue
        ref, dist = grid.nearest(xy[0], xy[1])
        # The grid registers candidates generously; the radius is the caller's
        # to enforce.
        if ref is None or dist > snap_m:
            continue
        out.setdefault(ref, []).append(_props(feat))
    return out


def _street_name(props: dict) -> str:
    for key in ("name", "street_name", "ref"):
        value = props.get(key)
        if value:
            return str(value)
    return ""


# ─── Small numeric helpers ───────────────────────────────────────────────────


def _ramp_up(value: float, low: float, high: float) -> float:
    """0.0 at or below ``low``, 1.0 at or above ``high``, linear between."""
    if high <= low:
        return 1.0 if value >= high else 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _ramp_down(value: float, good: float, bad: float) -> float:
    """1.0 at or below ``good``, 0.0 at or above ``bad``, linear between."""
    if bad <= good:
        return 1.0 if value <= good else 0.0
    return max(0.0, min(1.0, (bad - value) / (bad - good)))


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None


def _to_int(value):
    number = _to_float(value)
    return None if number is None else int(number)
