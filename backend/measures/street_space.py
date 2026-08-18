"""Street-space budget — where does the room for a redesign come from?

A protected cycle lane is never free. It costs kerbside parking, a motor-traffic
lane, or carriageway width. A plan that hides that trade-off is useless in a
council chamber, so OpenMobility OS states it explicitly for every segment it
proposes to rebuild.

This module is the transparent parameter catalogue behind that statement. It is
deliberately pure (no Django models, no I/O) so it can be unit-tested without a
database, and every number carries a source and can be overridden per workspace
via ``Workspace.settings["street_space"]`` — street design standards differ by
country, so nothing here may be hard-wired.

Honesty rule enforced throughout: when the underlying data does not say how wide
a street is, this module returns ``None`` / ``"unknown"``. It never invents a
width.
"""

from dataclasses import dataclass, field
from typing import Any

# ─── Default parameters ──────────────────────────────────────────────────────
# Conservative, widely used values. They are defaults, not truth: a municipality
# whose design standard differs overrides them per workspace.
DEFAULT_PARAMS: dict[str, Any] = {
    # Kerbside parking: length of carriageway consumed per parked car, by the
    # orientation of the parking bay.
    "parking_space_length_m": {
        "parallel": 5.75,
        "diagonal": 3.5,
        "perpendicular": 2.5,
    },
    # Width of carriageway released when a parking lane is removed.
    "parking_lane_width_m": {
        "parallel": 2.0,
        "diagonal": 4.5,
        "perpendicular": 5.0,
    },
    # Assumed width of one motor-traffic lane when OSM records `lanes` but not
    # `width`. Used only to *estimate*, and always flagged as an estimate.
    "car_lane_width_m": 3.0,
    # Width a rebuilt element needs, per intervention.
    "required_width_m": {
        "protected_bike_lane": 2.3,
        "safe_crossing": 0.0,
        "speed_limit_30": 0.0,
        "intersection_redesign": 0.0,
        "traffic_calming": 0.0,
    },
    # What has to be left over for motor traffic and emergency access after the
    # reallocation. Falling below this means the segment needs a bigger rebuild.
    "min_remaining_carriageway_m": 3.0,
    "source": {
        "title": "OpenMobility OS default street-space parameters",
        "note": (
            "Generic defaults. Replace with the design standard that applies in "
            "your jurisdiction via Workspace.settings['street_space']."
        ),
    },
}

# Order in which space is taken. Kerbside parking first — it is the cheapest and
# most reversible reallocation — then a motor-traffic lane, then narrowing what
# is left.
SPACE_ORDER = ("parking_removal", "lane_reallocation", "carriageway_narrowing")


def params_for(workspace=None) -> dict[str, Any]:
    """Merge the per-workspace overrides over the defaults (one level deep)."""
    overrides = {}
    if workspace is not None:
        overrides = (getattr(workspace, "settings", None) or {}).get("street_space") or {}
    merged = dict(DEFAULT_PARAMS)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


# ─── Parking ─────────────────────────────────────────────────────────────────

def estimated_parking_spaces(length_m, orientation="parallel", *, params=None) -> int | None:
    """How many cars fit along ``length_m`` of kerb, or None if unknowable.

    Returns None rather than 0 when the length is missing, so callers can tell
    "no parking here" apart from "we do not know".
    """
    if length_m is None:
        return None
    try:
        length = float(length_m)
    except (TypeError, ValueError):
        return None
    if length <= 0:
        return 0
    p = params or DEFAULT_PARAMS
    per_space = p["parking_space_length_m"].get(
        orientation, p["parking_space_length_m"]["parallel"]
    )
    if not per_space:
        return None
    return int(length // per_space)


def parking_width(orientation="parallel", *, params=None) -> float:
    p = params or DEFAULT_PARAMS
    return float(
        p["parking_lane_width_m"].get(orientation, p["parking_lane_width_m"]["parallel"])
    )


# ─── Available width ─────────────────────────────────────────────────────────

def available_width(street_props: dict, *, params=None) -> tuple[float | None, str]:
    """Best available reading of a carriageway's width.

    Returns ``(width_m, confidence)`` where confidence is one of:

    ``"tagged"``     — the source carries an explicit width
    ``"estimated"``  — derived from the lane count times an assumed lane width
    ``"unknown"``    — the data does not support any reading; width is None

    The ``unknown`` case is not a failure. It is the honest answer, and callers
    must surface it as "check on site" rather than substituting a guess.
    """
    p = params or DEFAULT_PARAMS
    raw_width = street_props.get("width_m", street_props.get("width"))
    width = _to_float(raw_width)
    if width is not None and width > 0:
        return width, "tagged"

    lanes = _to_float(street_props.get("lanes"))
    if lanes is not None and lanes > 0:
        return lanes * float(p["car_lane_width_m"]), "estimated"

    return None, "unknown"


@dataclass
class SpaceOption:
    """One concrete way to free up the required width on a segment."""

    kind: str  # one of SPACE_ORDER
    width_gained_m: float
    parking_spaces_removed: int = 0
    car_lanes_reallocated: int = 0
    detail: dict = field(default_factory=dict)


@dataclass
class SpaceBudget:
    """The full space verdict for one proposed segment rebuild."""

    required_width_m: float
    available_width_m: float | None
    width_confidence: str  # tagged | estimated | unknown
    space_source: str  # a SPACE_ORDER value, "not_needed", "unknown" or "insufficient"
    options: list[SpaceOption] = field(default_factory=list)
    parking_spaces_removed: int = 0
    car_lanes_reallocated: int = 0
    obstacles: list[dict] = field(default_factory=list)

    @property
    def needs_site_check(self) -> bool:
        return self.width_confidence != "tagged"


def plan_space(
    intervention: str,
    street_props: dict,
    *,
    parking_features: list[dict] | None = None,
    obstacles: list[dict] | None = None,
    segment_length_m: float | None = None,
    params=None,
) -> SpaceBudget:
    """Work out whether — and at whose expense — an intervention fits.

    Applies :data:`SPACE_ORDER` until the required width is covered. Every
    outcome is reported, including the two uncomfortable ones: ``"unknown"``
    (the data cannot say) and ``"insufficient"`` (it does not fit even after
    removing all parking and a lane). Neither causes the caller to drop the
    segment — a segment that is hard to rebuild is still a segment where people
    are being hurt.
    """
    p = params or DEFAULT_PARAMS
    required = float(p["required_width_m"].get(intervention, 0.0))
    width, confidence = available_width(street_props, params=p)
    obstacles = list(obstacles or [])

    if required <= 0:
        return SpaceBudget(
            required_width_m=required,
            available_width_m=width,
            width_confidence=confidence,
            space_source="not_needed",
            obstacles=obstacles,
        )

    options: list[SpaceOption] = []
    gained = 0.0
    parking_removed = 0
    lanes_reallocated = 0

    # 1. Kerbside parking.
    for feat in parking_features or []:
        props = feat.get("properties") or feat
        orientation = props.get("orientation") or "parallel"
        length = props.get("length_m", segment_length_m)
        spaces = props.get("estimated_spaces")
        if spaces is None:
            spaces = estimated_parking_spaces(length, orientation, params=p) or 0
        side_count = 2 if props.get("side") == "both" else 1
        w = parking_width(orientation, params=p) * side_count
        options.append(
            SpaceOption(
                kind="parking_removal",
                width_gained_m=w,
                parking_spaces_removed=int(spaces) * side_count,
                detail={"orientation": orientation, "side": props.get("side")},
            )
        )
        gained += w
        parking_removed += int(spaces) * side_count
        if gained >= required:
            break

    # 2. A motor-traffic lane, if parking was not enough.
    if gained < required:
        lanes = _to_float(street_props.get("lanes")) or 0
        lane_w = float(p["car_lane_width_m"])
        # Never take the last lane: a street needs to stay passable.
        while gained < required and lanes - lanes_reallocated > 1:
            lanes_reallocated += 1
            gained += lane_w
            options.append(
                SpaceOption(
                    kind="lane_reallocation",
                    width_gained_m=lane_w,
                    car_lanes_reallocated=1,
                )
            )

    # 3. Narrowing whatever carriageway is left.
    if gained < required and width is not None:
        spare = width - gained - float(p["min_remaining_carriageway_m"])
        if spare > 0:
            take = min(spare, required - gained)
            gained += take
            options.append(
                SpaceOption(kind="carriageway_narrowing", width_gained_m=round(take, 2))
            )

    if gained >= required:
        # Report the largest contributor as the headline source. Where several
        # were needed, the per-kind totals (parking spaces, lanes) still carry
        # the full picture, so nothing is hidden by picking one label.
        source = (
            max(options, key=lambda o: o.width_gained_m).kind if options else "not_needed"
        )
    elif confidence == "unknown":
        # We cannot prove it fits, but we also cannot prove it does not. Say so.
        source = "unknown"
    else:
        source = "insufficient"

    return SpaceBudget(
        required_width_m=required,
        available_width_m=width,
        width_confidence=confidence,
        space_source=source,
        options=options,
        parking_spaces_removed=parking_removed,
        car_lanes_reallocated=lanes_reallocated,
        obstacles=obstacles,
    )


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None
