"""Rule: cycling-accident infrastructure gaps.

Snaps cyclist accidents onto the street network and flags streets that carry a
high cyclist-accident score *and* have no bike infrastructure nearby. These are
the concrete segments a city should prioritise for protected cycling lanes.

This is the data-driven, geometry-bearing complement to
``rule_missing_protected_bike_lane`` (which only counts main streets vs. bike
ways). The candidate carries a ``MultiLineString`` geometry so the affected
streets render directly on the map's Measures layer.
"""

from django.contrib.gis.geos import GEOSGeometry, MultiLineString

from ..accident_density import (
    DEFAULT_GAP_M,
    DEFAULT_MIN_SCORE,
    DEFAULT_SNAP_M,
    find_cycling_gaps,
)
from ._common import MeasureCandidate, score, select_by_layer

_MAX_LISTED = 10  # cap the evidence list so it stays readable


def rule_cycling_infrastructure_gap(workspace, feature_sets):
    accidents_fs = select_by_layer(feature_sets, "accidents")
    streets_fs = select_by_layer(feature_sets, "streets_with_speed") or select_by_layer(
        feature_sets, "streets"
    )
    bike_fs = select_by_layer(feature_sets, "bike_network")

    if not accidents_fs or not streets_fs:
        return []

    accidents = accidents_fs.feature_collection.get("features", [])
    streets = streets_fs.feature_collection.get("features", [])
    bike_ways = bike_fs.feature_collection.get("features", []) if bike_fs else []

    center = getattr(workspace, "center", None)
    if center is None:
        return []
    center_lonlat = (center.x, center.y)

    gaps = find_cycling_gaps(
        accidents,
        streets,
        bike_ways,
        center_lonlat=center_lonlat,
        snap_m=DEFAULT_SNAP_M,
        gap_m=DEFAULT_GAP_M,
        min_score=DEFAULT_MIN_SCORE,
    )
    if not gaps:
        return []

    geometry = _build_geometry(gaps)
    n = len(gaps)
    total_score = sum(g["severity_score"] for g in gaps)
    total_accidents = sum(g["cyclist_accident_count"] for g in gaps)
    top = gaps[: min(_MAX_LISTED, n)]

    top_lines_de = "\n".join(
        f"- {_name_de(g)}: {g['cyclist_accident_count']} Radunfälle "
        f"(Score {g['severity_score']})"
        for g in top
    )
    top_lines_en = "\n".join(
        f"- {_name_en(g)}: {g['cyclist_accident_count']} cyclist accidents "
        f"(score {g['severity_score']})"
        for g in top
    )

    # Stronger safety signal the more concentrated the cyclist harm is.
    safety_val = min(0.97, 0.78 + total_score / max(total_accidents * 6, 1))

    candidate = MeasureCandidate(
        slug="cycling-accident-infrastructure-gaps",
        category="bike_infra",
        title_de="Radinfrastruktur-Lücken an Unfallschwerpunkten",
        title_en="Cycling infrastructure gaps at accident hotspots",
        summary_de=(
            f"{n} Straßen mit erhöhtem Radunfall-Score und ohne nahegelegene "
            "Radinfrastruktur identifiziert. Geschützte Radwege priorisiert prüfen."
        ),
        summary_en=(
            f"{n} streets with elevated cyclist-accident scores and no nearby "
            "bike infrastructure identified. Prioritise protected cycle lanes."
        ),
        description_de_md=(
            "## Befund\n"
            f"Im Workspace **{workspace.name}** wurden **{n} Straßen** gefunden, "
            f"die zusammen **{total_accidents} Radunfälle** tragen, aber keine "
            f"Radinfrastruktur im Umkreis von {DEFAULT_GAP_M:.0f} m aufweisen.\n\n"
            "## Betroffene Straßen (Top)\n"
            f"{top_lines_de}\n\n"
            "## Vorschlag\n"
            "Auf diesen Abschnitten geschützte Radstreifen oder bauliche "
            "Radwege priorisiert prüfen und mit sicheren Querungen ergänzen.\n\n"
            "## Methodik\n"
            f"Unfälle werden im Umkreis von {DEFAULT_SNAP_M:.0f} m auf die nächste "
            "Straße projiziert. Schweregradgewichtung: tödlich×3, schwer×2, "
            f"leicht×1. Eine Straße gilt als Lücke, wenn ihr Radunfall-Score "
            f"≥ {DEFAULT_MIN_SCORE} ist und die nächste Radinfrastruktur weiter "
            f"als {DEFAULT_GAP_M:.0f} m entfernt liegt."
        ),
        description_en_md=(
            "## Finding\n"
            f"In workspace **{workspace.name}**, **{n} streets** were found that "
            f"together carry **{total_accidents} cyclist accidents** but have no "
            f"bike infrastructure within {DEFAULT_GAP_M:.0f} m.\n\n"
            "## Affected streets (top)\n"
            f"{top_lines_en}\n\n"
            "## Proposal\n"
            "Prioritise protected cycle lanes or physically separated paths on "
            "these segments, complemented by safe crossings.\n\n"
            "## Methodology\n"
            f"Accidents are snapped to the nearest street within {DEFAULT_SNAP_M:.0f} m. "
            "Severity weighting: fatal×3, serious×2, minor×1. A street is flagged "
            f"as a gap when its cyclist-accident score is ≥ {DEFAULT_MIN_SCORE} and "
            f"the nearest bike infrastructure is farther than {DEFAULT_GAP_M:.0f} m."
        ),
        effort_level="medium",
        geometry=geometry,
        evidence={
            "gap_street_count": n,
            "cyclist_accident_total": total_accidents,
            "severity_score_total": total_score,
            "snap_radius_m": DEFAULT_SNAP_M,
            "gap_radius_m": DEFAULT_GAP_M,
            "min_score": DEFAULT_MIN_SCORE,
            "streets": [
                {
                    "name": g["street_name"],
                    "cyclist_accident_count": g["cyclist_accident_count"],
                    "severity_score": g["severity_score"],
                    "nearest_bike_m": g["nearest_bike_m"],
                }
                for g in top
            ],
        },
        scores={
            "climate": score(0.55, "medium"),
            "safety": score(
                safety_val,
                "high",
                "Schließt Radinfrastruktur-Lücken an nachweislichen Unfallstellen.",
                "Closes cycling-infrastructure gaps at evidenced accident sites.",
            ),
            "quality_of_life": score(0.7, "medium"),
            "social": score(0.7, "medium"),
            "feasibility": score(0.55, "medium"),
            "cost": score(0.45, "medium"),
            "visibility": score(0.8, "high"),
            "political": score(0.7, "medium"),
            "goal_alignment": score(0.85, "high"),
        },
    )
    return [candidate]


def _build_geometry(gaps):
    """Combine gap street geometries into a single MultiLineString (SRID 4326)."""
    lines = []
    for g in gaps:
        geom = g["geometry"] or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        try:
            if gtype == "LineString" and len(coords) >= 2:
                lines.append(GEOSGeometry(_linestring_json(coords), srid=4326))
            elif gtype == "MultiLineString":
                for line in coords:
                    if len(line) >= 2:
                        lines.append(GEOSGeometry(_linestring_json(line), srid=4326))
        except (ValueError, TypeError):
            continue
    if not lines:
        return None
    return MultiLineString(*lines, srid=4326)


def _linestring_json(coords):
    import json

    return json.dumps({"type": "LineString", "coordinates": coords})


def _name_de(g):
    return g["street_name"] or "Unbenannte Straße"


def _name_en(g):
    return g["street_name"] or "Unnamed street"
