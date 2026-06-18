"""Rule: urban heat vulnerability (depaving & greening).

Reads the open climate-readiness layers and flags a workspace as heat-
vulnerable when it carries a lot of sealed (impervious) surface relative to
its green cover and tree canopy. Hot, heavily-sealed, under-greened areas warm
up faster and cool down slower during heatwaves, so the rule proposes a
targeted depaving-and-greening measure.

Consumed layer kinds (all optional except ``sealed_surfaces``):
- ``sealed_surfaces`` — impervious-surface polygons (required signal)
- ``green_areas``      — parks / grass / meadow polygons (mitigation)
- ``trees``            — tree-cadastre points (mitigation / shade)
- ``heat_corridors``   — identified heat / fresh-air corridors (context)
- ``population_grid``  — residents exposed (raises the social weight)

The green-to-sealed comparison uses GEOS polygon areas in the workspace's own
coordinate reference. Areas are only ever compared against each other within
the same workspace, so the raw value is a transparent relative ratio — never a
cross-city absolute. The method is city-agnostic: it reads only generic layer
kinds, never a specific city, country, or data vendor.
"""

import json

from django.contrib.gis.geos import GEOSGeometry

from ._common import MeasureCandidate, score, select_by_layer

# Minimum number of sealed-surface polygons before the signal is trustworthy
# enough to act on — below this the OSM coverage is too sparse to judge.
MIN_SEALED_FEATURES = 5

# Green-to-sealed area ratio at or above which the workspace is considered
# adequately greened and the rule stays silent.
GREEN_RATIO_OK = 3.0

_OSM_SOURCE = {
    "name": "OpenStreetMap (Overpass)",
    "url": "https://www.openstreetmap.org/copyright",
}
_DWD_SOURCE = {
    "name": "Deutscher Wetterdienst (DWD) — heat-day climate indices",
    "url": "https://www.dwd.de/",
}


def rule_heat_vulnerability(workspace, feature_sets):
    sealed_fs = select_by_layer(feature_sets, "sealed_surfaces")
    if not sealed_fs:
        return []

    sealed_features = sealed_fs.feature_collection.get("features", [])
    sealed_count = len(sealed_features)
    if sealed_count < MIN_SEALED_FEATURES:
        return []

    sealed_area = _total_polygon_area(sealed_features)
    if sealed_area <= 0:
        return []

    green_fs = select_by_layer(feature_sets, "green_areas")
    green_features = green_fs.feature_collection.get("features", []) if green_fs else []
    green_area = _total_polygon_area(green_features)

    trees_fs = select_by_layer(feature_sets, "trees")
    tree_count = len(trees_fs.feature_collection.get("features", [])) if trees_fs else 0

    heat_fs = select_by_layer(feature_sets, "heat_corridors")
    heat_corridor_count = (
        len(heat_fs.feature_collection.get("features", [])) if heat_fs else 0
    )

    pop_fs = select_by_layer(feature_sets, "population_grid")
    residents = _total_population(pop_fs) if pop_fs else 0

    green_to_sealed = (green_area / sealed_area) if sealed_area > 0 else 0.0

    # Stay silent when the city is already well greened relative to its sealed
    # footprint and there are no flagged heat corridors to preserve.
    if green_to_sealed >= GREEN_RATIO_OK and heat_corridor_count == 0:
        return []

    # Green deficit: 0 when green cover already meets the OK ratio, →1 when
    # there is almost no green relative to sealed surface.
    green_deficit = max(0.0, 1.0 - (green_to_sealed / GREEN_RATIO_OK))
    climate_val = min(0.95, 0.4 + 0.5 * green_deficit)

    # Confidence rises when an authoritative heat-corridor layer corroborates
    # the OSM-derived sealing/green proxy.
    confidence = "high" if heat_corridor_count > 0 else "medium"

    sources = [_OSM_SOURCE]
    if heat_corridor_count > 0:
        sources.append(_DWD_SOURCE)

    # Social weight scales with the population actually exposed, when a grid is
    # available; otherwise it stays at a neutral medium.
    if residents > 0:
        social_val = min(0.9, 0.55 + min(residents, 200_000) / 400_000)
        social_conf = "medium"
    else:
        social_val = 0.6
        social_conf = "low"

    effort = "major"
    ratio_pct = round(green_to_sealed * 100, 1)

    summary_de = (
        f"{sealed_count} versiegelte Flächen erfasst; Grünflächen erreichen nur "
        f"{ratio_pct} % der versiegelten Fläche"
        + (f", {tree_count:,} Bäume im Baumkataster" if tree_count else "")
        + (f", {heat_corridor_count} Hitze-/Frischluftkorridore markiert" if heat_corridor_count else "")
        + "."
    )
    summary_en = (
        f"{sealed_count} sealed surfaces mapped; green areas cover only "
        f"{ratio_pct} % of the sealed footprint"
        + (f", {tree_count:,} trees in the cadastre" if tree_count else "")
        + (f", {heat_corridor_count} heat / fresh-air corridors flagged" if heat_corridor_count else "")
        + "."
    )

    return [
        MeasureCandidate(
            slug="entsiegelung-und-begruenung",
            category="public_space",
            title_de="Entsiegelung und Begrünung hitzebelasteter Quartiere",
            title_en="Depave and green heat-exposed neighborhoods",
            summary_de=summary_de,
            summary_en=summary_en,
            description_de_md=(
                "## Befund\n"
                f"Im Workspace **{workspace.name}** sind **{sealed_count} versiegelte "
                f"Flächen** erfasst. Die kartierten Grünflächen erreichen nur "
                f"**{ratio_pct} %** der versiegelten Fläche"
                + (f", ergänzt um **{tree_count:,} Bäume**" if tree_count else "")
                + (
                    f". Zudem sind **{heat_corridor_count} Hitze-/Frischluftkorridore** "
                    "ausgewiesen, die freigehalten werden müssen"
                    if heat_corridor_count
                    else ""
                )
                + ".\n\n"
                "Stark versiegelte, wenig begrünte Quartiere heizen sich bei "
                "Hitzewellen schneller auf und kühlen nachts kaum ab "
                "(städtische Hitzeinsel).\n\n"
                "## Vorschlag\n"
                "Versiegelte Flächen entsiegeln, Straßenbäume und Dach-/Fassaden- "
                "begrünung ergänzen und Frischluftkorridore von Bebauung freihalten. "
                "Schatten, Verdunstung und Versickerung senken die gefühlte "
                "Temperatur und puffern Starkregen.\n\n"
                "## Methodik\n"
                "Versiegelte und grüne Flächen werden als GEOS-Polygonflächen im "
                "Workspace-Koordinatensystem verglichen (relatives Verhältnis, kein "
                "stadtübergreifender Absolutwert). Datenbasis: OpenStreetMap"
                + (", Hitzekorridore aus DWD-/Klimaanalyse-Daten" if heat_corridor_count else "")
                + "."
            ),
            description_en_md=(
                "## Finding\n"
                f"Workspace **{workspace.name}** has **{sealed_count} sealed surfaces** "
                f"mapped. Mapped green areas cover only **{ratio_pct} %** of that sealed "
                f"footprint"
                + (f", alongside **{tree_count:,} trees**" if tree_count else "")
                + (
                    f". In addition, **{heat_corridor_count} heat / fresh-air corridors** "
                    "are flagged and must be kept clear"
                    if heat_corridor_count
                    else ""
                )
                + ".\n\n"
                "Heavily sealed, lightly greened areas warm up faster during "
                "heatwaves and barely cool at night (the urban heat-island effect).\n\n"
                "## Proposal\n"
                "Depave impervious surfaces, add street trees and roof/façade "
                "greening, and keep fresh-air corridors free of development. Shade, "
                "evaporation and infiltration lower the felt temperature and buffer "
                "heavy rain.\n\n"
                "## Methodology\n"
                "Sealed and green areas are compared as GEOS polygon areas in the "
                "workspace coordinate reference (a relative ratio, never a cross-city "
                "absolute). Data: OpenStreetMap"
                + (", heat corridors from DWD / climate-analysis data" if heat_corridor_count else "")
                + "."
            ),
            effort_level=effort,
            evidence={
                "sealed_feature_count": sealed_count,
                "sealed_area": round(sealed_area, 8),
                "green_area": round(green_area, 8),
                "green_to_sealed_ratio": round(green_to_sealed, 4),
                "green_deficit": round(green_deficit, 4),
                "tree_count": tree_count,
                "heat_corridor_count": heat_corridor_count,
                "residents_estimate": residents,
                "green_ratio_ok_threshold": GREEN_RATIO_OK,
            },
            scores={
                "climate": score(
                    climate_val,
                    confidence,
                    (
                        f"Grünanteil von nur {ratio_pct} % der versiegelten Fläche — "
                        "hohes Hitzeinsel-Risiko, klarer Handlungsbedarf bei Entsiegelung "
                        "und Begrünung."
                    ),
                    (
                        f"Green cover at just {ratio_pct} % of the sealed footprint — "
                        "high heat-island risk and a clear case for depaving and greening."
                    ),
                    sources=sources,
                ),
                "quality_of_life": score(
                    min(0.9, 0.55 + 0.4 * green_deficit),
                    "medium",
                    "Beschattung und kühlere Quartiere verbessern die Aufenthaltsqualität spürbar.",
                    "Shade and cooler neighborhoods noticeably improve livability.",
                ),
                "social": score(
                    social_val,
                    social_conf,
                    (
                        f"Schätzungsweise {residents:,} Einwohner:innen in der Analysefläche "
                        "profitieren von kühleren öffentlichen Räumen."
                        if residents > 0
                        else "Kühlere öffentliche Räume kommen besonders vulnerablen Gruppen zugute."
                    ),
                    (
                        f"An estimated {residents:,} residents in the analysis area benefit "
                        "from cooler public space."
                        if residents > 0
                        else "Cooler public space disproportionately helps vulnerable groups."
                    ),
                ),
                "feasibility": score(
                    0.45,
                    "medium",
                    "Entsiegelung ist baulich aufwendig, lässt sich aber schrittweise umsetzen.",
                    "Depaving is construction-heavy but can be delivered incrementally.",
                ),
                "cost": score(0.4, "medium"),
                "visibility": score(0.7, "medium"),
                "political": score(
                    0.65,
                    "medium",
                    "Hitzevorsorge ist politisch zunehmend gefragt und gut sichtbar.",
                    "Heat resilience is increasingly in political demand and highly visible.",
                ),
                "goal_alignment": score(
                    0.8,
                    "high",
                    "Direkter Beitrag zu Klimaanpassungs- und Begrünungszielen der Kommune.",
                    "Direct contribution to the municipality's climate-adaptation and greening goals.",
                ),
            },
        )
    ]


def _total_polygon_area(features) -> float:
    """Sum the GEOS area of all Polygon / MultiPolygon features.

    Returns a relative area in the squared units of SRID 4326. Used only for
    same-workspace ratios, never as an absolute measurement.
    """
    total = 0.0
    for f in features:
        geom = f.get("geometry") or {}
        gtype = geom.get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            continue
        try:
            total += GEOSGeometry(json.dumps(geom), srid=4326).area
        except (ValueError, TypeError):
            continue
    return total


def _total_population(pop_fs) -> int:
    """Best-effort resident count from a population-grid feature set.

    Mirrors the column fallbacks used by the equity rule; unknown schemas
    simply yield 0 (the social score then stays neutral).
    """
    total = 0
    for f in pop_fs.feature_collection.get("features", []):
        props = f.get("properties") or {}
        value = props.get("Einwohner")
        if value in (None, "", "-"):
            value = props.get("population")
        try:
            total += int(value)
        except (ValueError, TypeError):
            continue
    return total
