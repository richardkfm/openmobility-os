"""Intervention finders for road-safety targets.

These reuse the analysis the platform already trusts — ``find_cycling_gaps`` and
``aggregate_by_street`` from :mod:`measures.accident_density`, which snap crashes
onto the street network on a metric plane anchored at the workspace centre and
weight them by severity. Nothing here re-implements that; it only restricts the
input to the focus area and turns the result into concrete segment proposals.

The accidents handed in have already been filtered to the target's indicator
(severity classes, involved modes, year window), so a per-street
``accident_count`` *is* the number of cases the target is measured in, and
``fatal``/``serious`` on the same aggregate says whether that harm includes
someone killed or seriously injured.
"""

from ..accident_density import (
    DEFAULT_GAP_M,
    DEFAULT_MIN_SCORE,
    DEFAULT_SNAP_M,
    aggregate_by_street,
    find_cycling_gaps,
)
from ._common import InterventionCandidate

# A street is only proposed for a 30 km/h limit when it is posted at or above
# this and carries recorded harm. Overridable per workspace.
DEFAULT_SPEED_THRESHOLD = 50


def find_cycling_interventions(context):
    """Streets with cyclist harm and no cycling infrastructure → protected lane."""
    streets = context.streets
    bike_ways = context.layer("dedicated_bike_network") or context.layer("bike_network")
    if not context.indicator_accidents or not streets:
        return []

    gaps = find_cycling_gaps(
        context.layer("accidents"),
        streets,
        bike_ways,
        center_lonlat=context.center_lonlat,
        snap_m=DEFAULT_SNAP_M,
        gap_m=DEFAULT_GAP_M,
        min_score=DEFAULT_MIN_SCORE,
    )
    if not gaps:
        return []

    per_street, meta, _contributing, _unsnapped = aggregate_by_street(
        context.indicator_accidents,
        streets,
        center_lonlat=context.center_lonlat,
        snap_m=DEFAULT_SNAP_M,
    )

    candidates = []
    for gap in gaps:
        idx = gap["street_index"]
        agg = per_street.get(idx)
        if not agg or not agg["accident_count"]:
            # The street is a cycling-infrastructure gap, but carries no harm of
            # the kind this target measures. Proposing it here would inflate the
            # plan with work that cannot move the target.
            continue
        info = meta[idx] if idx < len(meta) else None
        street_props = context.street_props(idx)
        geometry = gap["geometry"] or (info or {}).get("geometry")

        candidates.append(
            InterventionCandidate(
                key=f"bike-{idx}",
                intervention="protected_bike_lane",
                title_de=(
                    f"Geschützter Radweg: {gap['street_name'] or 'unbenannte Straße'}"
                ),
                title_en=(
                    f"Protected cycle lane: {gap['street_name'] or 'unnamed street'}"
                ),
                geometry=geometry,
                quantity=context.length_m(geometry),
                affected_cases=float(agg["accident_count"]),
                severe=bool(agg["fatal"] or agg["serious"]),
                street_props=street_props,
                parking_features=context.parking_for(street_props),
                obstacles=context.obstacles_for(street_props),
                evidence={
                    "street_name": gap["street_name"],
                    "cases_in_target_indicator": agg["accident_count"],
                    "fatal": agg["fatal"],
                    "serious": agg["serious"],
                    "minor": agg["minor"],
                    "cyclist_severity_score": gap["severity_score"],
                    "nearest_bike_m": gap["nearest_bike_m"],
                    "snap_radius_m": DEFAULT_SNAP_M,
                    "gap_radius_m": DEFAULT_GAP_M,
                    "min_score": DEFAULT_MIN_SCORE,
                },
            )
        )
    return candidates


def find_speed_interventions(context):
    """Streets posted at or above the threshold that carry harm → 30 km/h."""
    streets = context.layer("streets_with_speed")
    if not context.indicator_accidents or not streets:
        return []

    threshold = context.setting("speed_threshold_kmh", DEFAULT_SPEED_THRESHOLD)
    per_street, meta, _contributing, _unsnapped = aggregate_by_street(
        context.indicator_accidents,
        streets,
        center_lonlat=context.center_lonlat,
        snap_m=DEFAULT_SNAP_M,
    )

    candidates = []
    for idx, agg in per_street.items():
        info = meta[idx] if idx < len(meta) else None
        if info is None or not agg["accident_count"]:
            continue
        props = (streets[idx].get("properties") or {}) if idx < len(streets) else {}
        speed = _to_int(props.get("maxspeed"))
        if speed is None or speed < threshold:
            continue
        geometry = info.get("geometry")
        candidates.append(
            InterventionCandidate(
                key=f"speed-{idx}",
                intervention="speed_limit_30",
                title_de=f"Tempo 30: {info.get('name') or 'unbenannte Straße'}",
                title_en=f"30 km/h limit: {info.get('name') or 'unnamed street'}",
                geometry=geometry,
                quantity=context.length_m(geometry),
                affected_cases=float(agg["accident_count"]),
                severe=bool(agg["fatal"] or agg["serious"]),
                street_props=props,
                obstacles=context.obstacles_for(props),
                evidence={
                    "street_name": info.get("name"),
                    "posted_speed": speed,
                    "threshold_kmh": threshold,
                    "cases_in_target_indicator": agg["accident_count"],
                    "fatal": agg["fatal"],
                    "serious": agg["serious"],
                    "minor": agg["minor"],
                    "severity_score": agg["severity_score"],
                },
            )
        )
    return candidates


def _to_int(value):
    try:
        return int(float(str(value).split()[0]))
    except (TypeError, ValueError, IndexError):
        return None
