"""Rule: accident cluster detection.

Uses accident data when available. Note: full accident modeling with
involved-mode classification (pedestrian, cyclist, truck, ...) is planned
for Phase 8 — see project roadmap in plan file and CHANGELOG.
"""

from ._common import MeasureCandidate, score, select_by_layer


def rule_accident_cluster(workspace, feature_sets):
    accidents_fs = select_by_layer(feature_sets, "accidents")
    if not accidents_fs:
        return []

    accidents = accidents_fs.feature_collection.get("features", [])
    if len(accidents) < 5:
        return []

    severe = [
        a
        for a in accidents
        if (a.get("properties") or {}).get("severity") in {"fatal", "serious"}
    ]

    return [
        MeasureCandidate(
            slug="accident-hotspot-review",
            category="speed",
            title_de="Prüfung von Unfall-Hotspots",
            title_en="Accident hotspot review",
            summary_de=(
                f"{len(accidents)} erfasste Unfälle, davon {len(severe)} schwer/tödlich. "
                "Verkehrsberuhigung oder Kreuzungsumbau empfohlen."
            ),
            summary_en=(
                f"{len(accidents)} recorded accidents, of which {len(severe)} severe/fatal. "
                "Traffic calming or intersection redesign recommended."
            ),
            description_de_md=(
                "## Befund\n"
                f"Im Workspace {workspace.name} liegen {len(accidents)} Unfälle im "
                f"Datensatz vor, darunter {len(severe)} mit schwerem Ausgang.\n\n"
                "## Vorschlag\n"
                "Unfall-Cluster priorisiert untersuchen und für die Top-Hotspots "
                "Maßnahmen wie Kreuzungsumbau, protektierte Abbiegespuren, Tempo-30 "
                "oder Sichtachsen-Freilegung prüfen.\n\n"
                "## Hinweis\n"
                "Die vollständige Auswertung nach Verkehrsteilnehmer-Typ (Fußgänger:in, "
                "Radfahrer:in, LKW usw.) ist für eine spätere Ausbaustufe "
                "vorgesehen."
            ),
            description_en_md=(
                "## Finding\n"
                f"In workspace {workspace.name}, {len(accidents)} accidents are on "
                f"record, {len(severe)} of them severe.\n\n"
                "## Proposal\n"
                "Investigate accident clusters and, for top hotspots, evaluate "
                "intersection redesign, protected turn lanes, 30 km/h zones, or "
                "sight-line improvements.\n\n"
                "## Note\n"
                "Full breakdown by mode of transport (pedestrian, cyclist, truck, ...) "
                "is planned for a later phase."
            ),
            effort_level="medium",
            evidence={"accident_count": len(accidents), "severe_count": len(severe)},
            scores={
                "climate": score(0.25, "low"),
                "safety": score(0.9, "high",
                                "Unfallschwerpunkte reduzieren — direkter Sicherheitsgewinn.",
                                "Reducing accident hotspots — direct safety gain."),
                "quality_of_life": score(0.55, "medium"),
                "social": score(0.6, "medium"),
                "feasibility": score(0.6, "medium"),
                "cost": score(0.5, "medium"),
                "visibility": score(0.7, "medium"),
                "political": score(0.7, "medium"),
                "goal_alignment": score(0.75, "medium"),
            },
        )
    ]
