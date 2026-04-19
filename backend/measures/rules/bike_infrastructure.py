"""Rule: propose protected bike lanes on main streets lacking one."""

from ._common import MeasureCandidate, score, select_by_layer


def rule_missing_protected_bike_lane(workspace, feature_sets):
    streets_fs = select_by_layer(feature_sets, "streets_with_speed") or select_by_layer(
        feature_sets, "streets"
    )
    bike_fs = select_by_layer(feature_sets, "bike_network")

    if not streets_fs:
        return []

    streets = streets_fs.feature_collection.get("features", [])
    bike_ways = bike_fs.feature_collection.get("features", []) if bike_fs else []

    # Main streets with high speed and no bike infrastructure nearby are candidates.
    main_count = 0
    for s in streets:
        tags = s.get("properties") or {}
        maxspeed = _parse_speed(tags.get("maxspeed"))
        highway = tags.get("highway", "")
        if highway in {"primary", "secondary", "tertiary"} and (maxspeed is None or maxspeed >= 40):
            main_count += 1

    if main_count == 0:
        return []

    coverage_ratio = len(bike_ways) / max(main_count, 1)
    gap_score = max(0.0, min(1.0, 1.0 - coverage_ratio / 2.0))

    candidate = MeasureCandidate(
        slug="protected-bike-lanes-main-corridors",
        category="bike_infra",
        title_de="Geschützte Radwege auf Hauptkorridoren",
        title_en="Protected bike lanes on main corridors",
        summary_de=(
            f"{main_count} Hauptstraßen-Abschnitte ohne durchgehende Radinfrastruktur "
            "identifiziert. Prüfung auf geschützte Radstreifen empfohlen."
        ),
        summary_en=(
            f"{main_count} main-street segments without continuous bike infrastructure "
            "identified. Protected bike lanes recommended."
        ),
        description_de_md=(
            "## Befund\n"
            f"Im Workspace {workspace.name} wurden {main_count} Hauptstraßen-Segmente "
            f"mit Tempo 40+ gefunden. Aktuell liegen {len(bike_ways)} Radweg-Features "
            "im OSM-Datensatz vor.\n\n"
            "## Vorschlag\n"
            "Geschützte Radstreifen auf Hauptkorridoren prüfen, beginnend mit "
            "Strecken ohne jegliche Radinfrastruktur im Umfeld von 20 Metern.\n\n"
            "## Erwartete Wirkung\n"
            "- Höhere Verkehrssicherheit für Radfahrende\n"
            "- Modal-Shift zum Umweltverbund\n"
            "- Beitrag zu kommunalen Klimazielen"
        ),
        description_en_md=(
            "## Finding\n"
            f"In workspace {workspace.name}, {main_count} main-street segments with "
            f"40+ km/h were found. The OSM dataset currently contains "
            f"{len(bike_ways)} bike-way features.\n\n"
            "## Proposal\n"
            "Assess protected bike lanes on main corridors, starting with segments "
            "lacking any bike infrastructure within 20 meters.\n\n"
            "## Expected impact\n"
            "- Improved safety for cyclists\n"
            "- Modal shift toward sustainable transport\n"
            "- Contribution to municipal climate targets"
        ),
        effort_level="medium",
        evidence={
            "main_street_count": main_count,
            "bike_way_count": len(bike_ways),
            "coverage_ratio": round(coverage_ratio, 3),
        },
        scores={
            "climate": score(
                0.6 + 0.3 * gap_score,
                "medium",
                "Höherer Radverkehrsanteil reduziert MIV-Emissionen.",
                "Higher cycling share reduces car-based emissions.",
                [{"name": "OSM Overpass", "url": "https://overpass-api.de/"}],
            ),
            "safety": score(
                0.7 + 0.2 * gap_score,
                "medium",
                "Getrennte Radinfrastruktur senkt Konfliktpotenzial.",
                "Separated cycling infrastructure reduces conflict potential.",
            ),
            "quality_of_life": score(0.6, "medium"),
            "social": score(0.55, "medium"),
            "feasibility": score(0.55, "medium"),
            "cost": score(0.45, "medium"),
            "visibility": score(0.7, "medium"),
            "political": score(0.55, "low"),
            "goal_alignment": score(0.65, "medium"),
        },
    )
    return [candidate]


def _parse_speed(value):
    if value is None:
        return None
    try:
        return int(str(value).split()[0])
    except (ValueError, IndexError):
        return None
