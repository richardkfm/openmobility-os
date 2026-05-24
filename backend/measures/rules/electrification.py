"""Rule: EV-charging gap.

Compares the number of public EV chargers in the workspace against the
resident population. Flags workspaces whose charger-to-resident ratio falls
materially short of the EU AFIR 2030 reference value (≈100 residents per
1 charging point, derived from a 1 kW-per-EV national fleet target). When
no population figure is recorded on the workspace, falls back to an absolute
density floor so the rule still fires for under-equipped municipalities.

Layer kind consumed: ``ev_charging`` (typically populated by the
Bundesnetzagentur Ladesäulenregister, BAFA, OpenChargeMap, or the OSM
``ev_chargers_osm`` template).
"""

from ._common import MeasureCandidate, score, select_by_layer

AFIR_2030_RESIDENTS_PER_CHARGER = 100
MIN_CHARGERS_PER_SQKM = 0.5


def rule_ev_charging_gap(workspace, feature_sets):
    chargers_fs = select_by_layer(feature_sets, "ev_charging")
    if not chargers_fs:
        return []

    chargers = chargers_fs.feature_collection.get("features", [])
    n_chargers = len(chargers)

    population = getattr(workspace, "population", None) or 0
    area = float(getattr(workspace, "area_km2", None) or 0)

    residents_per_charger = (
        population / n_chargers if (population and n_chargers) else None
    )
    chargers_per_sqkm = (n_chargers / area) if area else None

    pop_shortfall = (
        residents_per_charger is not None
        and residents_per_charger > AFIR_2030_RESIDENTS_PER_CHARGER
    )
    density_shortfall = (
        chargers_per_sqkm is not None and chargers_per_sqkm < MIN_CHARGERS_PER_SQKM
    )

    if not (pop_shortfall or density_shortfall):
        return []

    if residents_per_charger:
        target_chargers = int(population / AFIR_2030_RESIDENTS_PER_CHARGER)
        needed_extra = max(0, target_chargers - n_chargers)
    else:
        needed_extra = max(0, int((MIN_CHARGERS_PER_SQKM * area) - n_chargers))

    safety_val = min(0.9, 0.5 + (needed_extra / max(n_chargers + needed_extra, 1)) * 0.4)

    rationale_de = (
        f"{n_chargers} öffentliche Ladepunkte im Workspace. "
        + (
            f"Verhältnis: {residents_per_charger:.0f} Einwohner:innen pro Ladepunkt "
            f"(EU-AFIR-Zielwert 2030: {AFIR_2030_RESIDENTS_PER_CHARGER}). "
            if residents_per_charger
            else ""
        )
        + (
            f"Dichte: {chargers_per_sqkm:.2f} pro km² (Minimum-Richtwert: {MIN_CHARGERS_PER_SQKM})."
            if chargers_per_sqkm is not None
            else ""
        )
    )
    rationale_en = (
        f"{n_chargers} public charging points in the workspace. "
        + (
            f"Ratio: {residents_per_charger:.0f} residents per point "
            f"(EU AFIR 2030 reference: {AFIR_2030_RESIDENTS_PER_CHARGER}). "
            if residents_per_charger
            else ""
        )
        + (
            f"Density: {chargers_per_sqkm:.2f} per km² (floor: {MIN_CHARGERS_PER_SQKM})."
            if chargers_per_sqkm is not None
            else ""
        )
    )

    return [
        MeasureCandidate(
            slug="ev-charging-buildout",
            category="electrification",
            title_de="Ausbau öffentlicher Ladeinfrastruktur",
            title_en="Public EV charging buildout",
            summary_de=(
                f"{n_chargers} Ladepunkte erfasst — etwa {needed_extra} weitere bis 2030 "
                "nötig, um den AFIR-Referenzwert zu erreichen."
            ),
            summary_en=(
                f"{n_chargers} charging points on record — about {needed_extra} additional "
                "ones needed by 2030 to reach the AFIR reference."
            ),
            description_de_md=(
                "## Befund\n"
                f"In **{workspace.name}** sind aktuell **{n_chargers} öffentliche Ladepunkte** im "
                "Datensatz hinterlegt. "
                + (
                    f"Das entspricht **{residents_per_charger:.0f} Einwohner:innen pro Ladepunkt** "
                    f"(EU-AFIR-Zielwert 2030: ≈{AFIR_2030_RESIDENTS_PER_CHARGER}).\n\n"
                    if residents_per_charger
                    else ""
                )
                + "## Vorschlag\n"
                "Priorisierter Ausbau öffentlicher Ladepunkte mit Schwerpunkt auf "
                "unterversorgten Quartieren und an wichtigen Mobilitäts-Knoten "
                "(Bahnhöfe, P+R, Einkaufszentren).\n\n"
                "## Methodik\n"
                "Vergleich der gemeldeten Ladepunkte (z. B. Bundesnetzagentur, OSM) "
                "mit dem AFIR-Referenzwert von 1 Ladepunkt pro 100 Einwohner:innen "
                "und einer Mindestdichte von 0,5 Punkten pro km²."
            ),
            description_en_md=(
                "## Finding\n"
                f"**{workspace.name}** currently has **{n_chargers} public charging points** "
                "on record. "
                + (
                    f"That's **{residents_per_charger:.0f} residents per point** "
                    f"(EU AFIR 2030 reference: ≈{AFIR_2030_RESIDENTS_PER_CHARGER}).\n\n"
                    if residents_per_charger
                    else ""
                )
                + "## Proposal\n"
                "Prioritized rollout of public charging, focused on under-served "
                "neighbourhoods and high-traffic mobility nodes "
                "(train stations, P+R, retail).\n\n"
                "## Methodology\n"
                "Reported chargers (e.g. Bundesnetzagentur, OSM) are compared "
                "against the AFIR reference of 1 charger per 100 residents and "
                "a floor density of 0.5 chargers per km²."
            ),
            effort_level="major",
            evidence={
                "charger_count": n_chargers,
                "residents_per_charger": (
                    round(residents_per_charger, 1) if residents_per_charger else None
                ),
                "chargers_per_sqkm": (
                    round(chargers_per_sqkm, 3) if chargers_per_sqkm is not None else None
                ),
                "needed_extra_by_2030": needed_extra,
                "afir_reference_residents_per_charger": AFIR_2030_RESIDENTS_PER_CHARGER,
            },
            scores={
                "climate": score(
                    0.8,
                    "high",
                    "Voraussetzung für die Elektrifizierung des MIV.",
                    "Prerequisite for car-fleet electrification.",
                ),
                "safety": score(0.25, "low"),
                "quality_of_life": score(0.5, "medium"),
                "social": score(
                    safety_val,
                    "medium",
                    "Gleichmäßige Verteilung verhindert Lade-Wüsten in Außenbezirken.",
                    "Even distribution prevents charging deserts in outer districts.",
                ),
                "feasibility": score(0.5, "medium"),
                "cost": score(0.35, "medium"),
                "visibility": score(0.65, "medium"),
                "political": score(0.55, "medium"),
                "goal_alignment": score(
                    0.7,
                    "medium",
                    rationale_de,
                    rationale_en,
                ),
            },
        )
    ]
