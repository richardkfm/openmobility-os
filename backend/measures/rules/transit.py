"""Rule: detect transit coverage gaps based on stop density."""

from ._common import MeasureCandidate, score, select_by_layer


def rule_transit_coverage_gap(workspace, feature_sets):
    stops_fs = select_by_layer(feature_sets, "transit_stops")
    if not stops_fs:
        return []

    stops = stops_fs.feature_collection.get("features", [])
    if not stops:
        return []

    population = workspace.population or 0
    stop_count = len(stops)
    # Reference: rule-of-thumb ~1 stop per 500 inhabitants in good urban coverage.
    expected = max(population / 500, 10) if population else 20
    gap_ratio = max(0.0, 1.0 - (stop_count / expected))

    if gap_ratio < 0.15:
        return []

    candidate = MeasureCandidate(
        slug="transit-coverage-extension",
        category="transit",
        title_de="ÖPNV-Netzverdichtung in unterversorgten Quartieren",
        title_en="Public transit coverage extension in underserved neighborhoods",
        summary_de=(
            f"{stop_count} Haltestellen erfasst, aber geschätzter Bedarf bei "
            f"~{int(expected)}. Verdichtung empfohlen."
        ),
        summary_en=(
            f"{stop_count} stops recorded vs. estimated need of ~{int(expected)}. "
            "Network extension recommended."
        ),
        description_de_md=(
            "## Befund\n"
            f"Im Workspace {workspace.name} stehen {stop_count} Haltestellen den "
            f"rund {population or '–'} Einwohnenden gegenüber. Das liegt unter "
            f"dem Richtwert von einer Haltestelle je 500 Einwohnenden.\n\n"
            "## Vorschlag\n"
            "Neue Linien oder Taktverdichtung in den Quartieren mit "
            "schwacher Anbindung prüfen. Details hängen vom ÖPNV-Konzept der "
            "Kommune ab.\n\n"
            "## Datenlage\n"
            "Aktuelle Grundlage: OpenStreetMap `public_transport=stop_position`, "
            "`highway=bus_stop`, `railway=tram_stop`. Empfehlung: zusätzlich GTFS "
            "einbinden, sobald der GTFS-Connector verfügbar ist."
        ),
        description_en_md=(
            "## Finding\n"
            f"In workspace {workspace.name}, {stop_count} stops serve approximately "
            f"{population or '–'} residents — below the rule-of-thumb of one stop "
            "per 500 residents.\n\n"
            "## Proposal\n"
            "Assess new routes or higher service frequency in underserved neighborhoods.\n\n"
            "## Data basis\n"
            "Currently: OpenStreetMap `public_transport=stop_position`, "
            "`highway=bus_stop`, `railway=tram_stop`. Recommendation: add GTFS "
            "once the GTFS connector is available."
        ),
        effort_level="major",
        evidence={
            "stop_count": stop_count,
            "estimated_need": int(expected),
            "population": population,
            "gap_ratio": round(gap_ratio, 3),
        },
        scores={
            "climate": score(0.55 + 0.2 * gap_ratio, "medium"),
            "safety": score(0.45, "low"),
            "quality_of_life": score(0.6 + 0.2 * gap_ratio, "medium"),
            "social": score(0.75, "high",
                            "Bessere ÖPNV-Anbindung senkt Mobilitätsarmut.",
                            "Better transit coverage reduces transport poverty."),
            "feasibility": score(0.45, "low"),
            "cost": score(0.35, "medium"),
            "visibility": score(0.55, "medium"),
            "political": score(0.5, "low"),
            "goal_alignment": score(0.6, "medium"),
        },
    )
    return [candidate]
