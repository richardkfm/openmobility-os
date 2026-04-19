"""Rule: unsafe school routes — triggered when schools are present."""

from ._common import MeasureCandidate, score, select_by_layer


def rule_unsafe_school_route(workspace, feature_sets):
    schools_fs = select_by_layer(feature_sets, "schools")
    if not schools_fs:
        return []

    schools = schools_fs.feature_collection.get("features", [])
    if not schools:
        return []

    return [
        MeasureCandidate(
            slug="school-street-pilot",
            category="school_routes",
            title_de="Pilotprojekt Schulstraßen",
            title_en="School streets pilot",
            summary_de=(
                f"{len(schools)} Schulen im Workspace. Schulstraßen an den 3 "
                "am stärksten frequentierten Standorten empfohlen."
            ),
            summary_en=(
                f"{len(schools)} schools in this workspace. School-streets pilot "
                "recommended at the 3 busiest locations."
            ),
            description_de_md=(
                "## Befund\n"
                f"Im Workspace {workspace.name} sind {len(schools)} Schulen erfasst. "
                "Für einen Pilotversuch \"Schulstraße\" können Standorte mit hohem "
                "Elterntaxi-Aufkommen oder komplexer Verkehrslage gewählt werden.\n\n"
                "## Vorschlag\n"
                "Temporäre oder dauerhafte Sperrung der unmittelbaren Zufahrt vor "
                "Schulbeginn und -ende für den motorisierten Durchgangsverkehr.\n\n"
                "## Erwartete Wirkung\n"
                "- Sicherere Schulwege\n"
                "- Mehr eigenständige Mobilität von Kindern\n"
                "- Reduktion des Elterntaxi-Aufkommens"
            ),
            description_en_md=(
                "## Finding\n"
                f"In workspace {workspace.name}, {len(schools)} schools are on record. "
                "A \"school street\" pilot can be launched at locations with high "
                "parent-taxi volume or complex traffic situations.\n\n"
                "## Proposal\n"
                "Temporary or permanent restriction of motorized through traffic at "
                "school start and end times.\n\n"
                "## Expected impact\n"
                "- Safer school routes\n"
                "- More independent mobility for children\n"
                "- Less parent-taxi traffic"
            ),
            effort_level="quick_win",
            evidence={"school_count": len(schools)},
            scores={
                "climate": score(0.4, "medium"),
                "safety": score(0.85, "high"),
                "quality_of_life": score(0.75, "medium"),
                "social": score(0.8, "high"),
                "feasibility": score(0.75, "medium"),
                "cost": score(0.85, "high"),
                "visibility": score(0.8, "medium"),
                "political": score(0.55, "low"),
                "goal_alignment": score(0.6, "medium"),
            },
        )
    ]
