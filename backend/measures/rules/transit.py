"""Transit measure rules — coverage gap, frequency, accessibility.

These rules consume the ``transit_stops`` layer and optionally
``transit_coverage``. When the feature set comes from the GTFS connector it
carries headway, night-service, modes and accessibility attributes; when it
comes from OSM it usually has only the stop name. Both paths are handled.
"""

from ._common import MeasureCandidate, score, select_by_layer

# Headway thresholds (minutes) — any stop whose average headway is longer than
# ``LOW_FREQUENCY_THRESHOLD_MIN`` counts as low-frequency.
LOW_FREQUENCY_THRESHOLD_MIN = 20
# A frequency gap measure is only proposed when at least this share of stops
# are below the threshold.
LOW_FREQUENCY_MIN_SHARE = 0.25
# An accessibility measure is only proposed when at least this share of stops
# are not barrier-free.
ACCESSIBILITY_MIN_SHARE = 0.2


def rule_transit_coverage_gap(workspace, feature_sets):
    """Coverage gap — compares stop count against a population-derived target."""
    stops_fs = select_by_layer(feature_sets, "transit_stops")
    if not stops_fs:
        return []

    stops = stops_fs.feature_collection.get("features", [])
    if not stops:
        return []

    population = workspace.population or 0
    stop_count = len(stops)
    # Rule-of-thumb: one stop per ~500 residents in good urban coverage.
    expected = max(population / 500, 10) if population else 20
    gap_ratio = max(0.0, 1.0 - (stop_count / expected))

    if gap_ratio < 0.15:
        return []

    candidate = MeasureCandidate(
        slug="transit-coverage-extension",
        category="transit_gap",
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
            "Grundlage: ``transit_stops``-Layer (GTFS oder OpenStreetMap). "
            "Der zugehörige ``transit_coverage``-Layer zeigt die 300–500 m "
            "Einzugsbereiche auf der Karte."
        ),
        description_en_md=(
            "## Finding\n"
            f"In workspace {workspace.name}, {stop_count} stops serve approximately "
            f"{population or '–'} residents — below the rule-of-thumb of one stop "
            "per 500 residents.\n\n"
            "## Proposal\n"
            "Assess new routes or higher service frequency in underserved neighborhoods.\n\n"
            "## Data basis\n"
            "Based on the ``transit_stops`` layer (GTFS or OpenStreetMap). The "
            "companion ``transit_coverage`` layer visualises 300–500 m stop "
            "catchment areas on the map."
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


def rule_transit_frequency(workspace, feature_sets):
    """Flag share of stops running below an acceptable daytime headway.

    Only meaningful when the feature set is enriched with ``avg_headway_min``
    (i.e. came from the GTFS connector). Stops without a headway value are
    excluded from the denominator.
    """
    stops_fs = select_by_layer(feature_sets, "transit_stops")
    if not stops_fs:
        return []

    stops = stops_fs.feature_collection.get("features", [])
    with_headway = [
        f for f in stops
        if (f.get("properties") or {}).get("avg_headway_min") is not None
    ]
    if not with_headway:
        return []

    low_freq = [
        f for f in with_headway
        if _as_float((f["properties"] or {}).get("avg_headway_min"))
        > LOW_FREQUENCY_THRESHOLD_MIN
    ]
    share = len(low_freq) / len(with_headway)
    if share < LOW_FREQUENCY_MIN_SHARE or len(low_freq) < 3:
        return []

    avg_low = sum(
        _as_float((f["properties"] or {}).get("avg_headway_min"))
        for f in low_freq
    ) / max(len(low_freq), 1)

    return [MeasureCandidate(
        slug="transit-frequency-upgrade",
        category="transit_frequency",
        title_de="Taktverdichtung auf schwach bedienten Linien",
        title_en="Frequency upgrade on underserved lines",
        summary_de=(
            f"{len(low_freq)} von {len(with_headway)} Haltestellen haben einen "
            f"durchschnittlichen Takt über {LOW_FREQUENCY_THRESHOLD_MIN} Minuten "
            f"(Ø {avg_low:.0f} min). Taktverdichtung empfohlen."
        ),
        summary_en=(
            f"{len(low_freq)} of {len(with_headway)} stops have an average "
            f"headway longer than {LOW_FREQUENCY_THRESHOLD_MIN} minutes "
            f"(avg {avg_low:.0f} min). Frequency upgrade recommended."
        ),
        description_de_md=(
            "## Befund\n"
            f"An **{len(low_freq)} Haltestellen** liegt die durchschnittliche "
            f"Taktfolge über **{LOW_FREQUENCY_THRESHOLD_MIN} Minuten**. Das "
            "liegt über der typischen Akzeptanzschwelle für einen "
            "verlässlichen ÖPNV.\n\n"
            "## Vorschlag\n"
            "- Fahrplanprüfung auf den betroffenen Linien\n"
            "- Taktverdichtung insbesondere in Haupt- und Nebenverkehrszeit\n"
            "- Ggf. zusätzliche Fahrzeuge oder Personalbedarf ermitteln\n\n"
            "## Methodik\n"
            "Durchschnittliche Taktfolge pro Halt = Service-Fenster (Default 16 h) ÷ "
            "täglichen Fahrten je Halt aus GTFS `stop_times.txt`."
        ),
        description_en_md=(
            "## Finding\n"
            f"At **{len(low_freq)} stops** the average headway exceeds "
            f"**{LOW_FREQUENCY_THRESHOLD_MIN} minutes** — above the typical "
            "acceptance threshold for reliable public transit.\n\n"
            "## Proposal\n"
            "- Review schedules on the affected lines\n"
            "- Increase frequency, especially in peak and shoulder hours\n"
            "- Assess additional vehicle / driver needs\n\n"
            "## Methodology\n"
            "Average headway per stop = service window (default 16 h) ÷ daily "
            "trips per stop, derived from GTFS `stop_times.txt`."
        ),
        effort_level="major",
        evidence={
            "low_freq_stops": len(low_freq),
            "total_stops_with_headway": len(with_headway),
            "share_low_freq": round(share, 3),
            "avg_low_freq_headway_min": round(avg_low, 1),
            "threshold_min": LOW_FREQUENCY_THRESHOLD_MIN,
        },
        scores={
            "climate": score(0.65, "medium"),
            "safety": score(0.4, "low"),
            "quality_of_life": score(0.75, "medium",
                                     "Verlässlicher Takt macht den ÖPNV attraktiver.",
                                     "Reliable frequency makes transit more attractive."),
            "social": score(0.75, "high"),
            "feasibility": score(0.45, "low"),
            "cost": score(0.3, "medium"),
            "visibility": score(0.55, "medium"),
            "political": score(0.5, "medium"),
            "goal_alignment": score(0.7, "medium"),
        },
    )]


def rule_transit_accessibility(workspace, feature_sets):
    """Flag stops that are not barrier-free.

    Works on any ``transit_stops`` feature set carrying a
    ``wheelchair_boarding`` property with values ``yes`` / ``no`` / ``unknown``
    (GTFS connector emits this directly; other connectors may populate it
    from source metadata).
    """
    stops_fs = select_by_layer(feature_sets, "transit_stops")
    if not stops_fs:
        return []

    stops = stops_fs.feature_collection.get("features", [])
    rated = [
        f for f in stops
        if (f.get("properties") or {}).get("wheelchair_boarding") in ("yes", "no")
    ]
    if not rated:
        return []

    not_barrier_free = [
        f for f in rated
        if (f["properties"] or {}).get("wheelchair_boarding") == "no"
    ]
    share = len(not_barrier_free) / len(rated)
    if share < ACCESSIBILITY_MIN_SHARE or len(not_barrier_free) < 3:
        return []

    return [MeasureCandidate(
        slug="transit-accessibility-upgrade",
        category="transit_accessibility",
        title_de="Barrierefreier Umbau von Haltestellen",
        title_en="Barrier-free upgrade of transit stops",
        summary_de=(
            f"{len(not_barrier_free)} von {len(rated)} bewerteten Haltestellen "
            "sind laut Daten nicht barrierefrei. Umbau priorisiert empfohlen."
        ),
        summary_en=(
            f"{len(not_barrier_free)} of {len(rated)} rated stops are not "
            "wheelchair-accessible. Prioritised upgrade recommended."
        ),
        description_de_md=(
            "## Befund\n"
            f"**{len(not_barrier_free)} Haltestellen** sind nach aktueller "
            "Datenlage nicht barrierefrei (`wheelchair_boarding = no`).\n\n"
            "## Vorschlag\n"
            "- Bordsteinabsenkungen und taktile Leitsysteme nachrüsten\n"
            "- Fahrscheinautomaten und Info-Displays in Hör- und Greifhöhe\n"
            "- Fahrzeuge mit stufenlosem Einstieg auf betroffenen Linien "
            "einsetzen\n\n"
            "## Wirkung\n"
            "Barrierefreie Haltestellen kommen allen Fahrgästen zugute "
            "(Senior:innen, Reisende mit Gepäck, Eltern mit Kinderwagen) und "
            "sind Grundvoraussetzung für die Teilhabe mobilitätseingeschränkter "
            "Menschen."
        ),
        description_en_md=(
            "## Finding\n"
            f"**{len(not_barrier_free)} stops** are currently not wheelchair-"
            "accessible (`wheelchair_boarding = no`).\n\n"
            "## Proposal\n"
            "- Retrofit curb cuts and tactile guidance systems\n"
            "- Ticket machines and info displays at accessible height\n"
            "- Deploy low-floor vehicles on the affected lines\n\n"
            "## Impact\n"
            "Accessible stops benefit every rider (seniors, travellers with "
            "luggage, parents with strollers) and are a prerequisite for the "
            "participation of people with reduced mobility."
        ),
        effort_level="major",
        evidence={
            "stops_rated": len(rated),
            "stops_not_barrier_free": len(not_barrier_free),
            "share_not_barrier_free": round(share, 3),
        },
        scores={
            "climate": score(0.2, "low"),
            "safety": score(0.45, "low"),
            "quality_of_life": score(0.7, "medium"),
            "social": score(0.9, "high",
                            "Barrierefreiheit ist essenziell für Teilhabe.",
                            "Accessibility is essential for participation."),
            "feasibility": score(0.55, "medium"),
            "cost": score(0.4, "medium"),
            "visibility": score(0.6, "medium"),
            "political": score(0.7, "medium"),
            "goal_alignment": score(0.75, "medium"),
        },
    )]


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
