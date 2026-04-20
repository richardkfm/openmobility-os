"""Rule: accident cluster detection — Phase 8 implementation.

Weights accidents by severity (fatal=3, serious=2, minor=1) and identifies
VRU (vulnerable road user) involvement to produce differentiated measures.
"""

from ._common import MeasureCandidate, score, select_by_layer

_SEVERITY_WEIGHT = {"fatal": 3, "serious": 2, "minor": 1}


def rule_accident_cluster(workspace, feature_sets):
    accidents_fs = select_by_layer(feature_sets, "accidents")
    if not accidents_fs:
        return []

    accidents = accidents_fs.feature_collection.get("features", [])
    if len(accidents) < 5:
        return []

    fatal = [a for a in accidents if _severity(a) == "fatal"]
    serious = [a for a in accidents if _severity(a) == "serious"]
    minor = [a for a in accidents if _severity(a) == "minor"]

    severity_score = (
        len(fatal) * _SEVERITY_WEIGHT["fatal"]
        + len(serious) * _SEVERITY_WEIGHT["serious"]
        + len(minor) * _SEVERITY_WEIGHT["minor"]
    )

    vru_accidents = [a for a in accidents if _is_vru(a)]
    vru_severe = [a for a in vru_accidents if _severity(a) in ("fatal", "serious")]

    measures = [_hotspot_measure(workspace, accidents, fatal, serious, severity_score)]

    if len(vru_accidents) >= 3:
        measures.append(_vru_measure(workspace, vru_accidents, vru_severe))

    return measures


def _severity(feature):
    return (feature.get("properties") or {}).get("severity", "minor")


def _is_vru(feature):
    props = feature.get("properties") or {}
    if props.get("vulnerable_road_user"):
        return True
    modes = props.get("involved_modes") or []
    if isinstance(modes, str):
        modes = [modes]
    return any(m in modes for m in ("cyclist", "pedestrian"))


def _hotspot_measure(workspace, accidents, fatal, serious, severity_score):
    n = len(accidents)
    safety_val = min(0.95, 0.6 + severity_score / (n * 10))

    return MeasureCandidate(
        slug="accident-hotspot-review",
        category="speed",
        title_de="Prüfung von Unfall-Hotspots",
        title_en="Accident hotspot review",
        summary_de=(
            f"{n} erfasste Unfälle (davon {len(fatal)} tödlich, {len(serious)} schwer). "
            "Verkehrsberuhigung oder Kreuzungsumbau empfohlen."
        ),
        summary_en=(
            f"{n} recorded accidents ({len(fatal)} fatal, {len(serious)} serious). "
            "Traffic calming or intersection redesign recommended."
        ),
        description_de_md=(
            "## Befund\n"
            f"Im Workspace **{workspace.name}** liegen **{n} Unfälle** im Datensatz vor "
            f"({len(fatal)} tödlich, {len(serious)} schwer, {n - len(fatal) - len(serious)} leicht). "
            f"Gewichteter Schweregradwert: {severity_score}.\n\n"
            "## Vorschlag\n"
            "Unfall-Cluster priorisiert untersuchen und für die Top-Hotspots Maßnahmen "
            "wie Kreuzungsumbau, protektierte Abbiegespuren, Tempo-30-Zonen oder "
            "Sichtachsen-Freilegung prüfen.\n\n"
            "## Methodik\n"
            "Schweregradgewichtung: tödlich×3, schwer×2, leicht×1. "
            "Hotspots werden nach gewichtetem Score absteigend sortiert."
        ),
        description_en_md=(
            "## Finding\n"
            f"In workspace **{workspace.name}**, **{n} accidents** are on record "
            f"({len(fatal)} fatal, {len(serious)} serious, {n - len(fatal) - len(serious)} minor). "
            f"Weighted severity score: {severity_score}.\n\n"
            "## Proposal\n"
            "Investigate accident clusters and, for top hotspots, evaluate "
            "intersection redesign, protected turn lanes, 30 km/h zones, or "
            "sight-line improvements.\n\n"
            "## Methodology\n"
            "Severity weighting: fatal×3, serious×2, minor×1. "
            "Hotspots are ranked by weighted score descending."
        ),
        effort_level="medium",
        evidence={
            "accident_count": n,
            "fatal_count": len(fatal),
            "serious_count": len(serious),
            "minor_count": len(accidents) - len(fatal) - len(serious),
            "severity_score": severity_score,
        },
        scores={
            "climate": score(0.25, "low"),
            "safety": score(
                safety_val,
                "high",
                "Unfallschwerpunkte reduzieren — direkter Sicherheitsgewinn.",
                "Reducing accident hotspots — direct safety gain.",
            ),
            "quality_of_life": score(0.55, "medium"),
            "social": score(0.6, "medium"),
            "feasibility": score(0.6, "medium"),
            "cost": score(0.5, "medium"),
            "visibility": score(0.7, "medium"),
            "political": score(0.75, "medium"),
            "goal_alignment": score(0.75, "medium"),
        },
    )


def _vru_measure(workspace, vru_accidents, vru_severe):
    n = len(vru_accidents)
    n_severe = len(vru_severe)
    safety_val = min(0.97, 0.75 + n_severe / max(n, 1) * 0.2)

    return MeasureCandidate(
        slug="vru-safety-intervention",
        category="safety",
        title_de="Schutz gefährdeter Verkehrsteilnehmer:innen",
        title_en="Vulnerable road user safety intervention",
        summary_de=(
            f"{n} Unfälle mit Beteiligung von Radfahrenden oder Fußgänger:innen "
            f"(davon {n_severe} schwer/tödlich). Separate Radinfrastruktur und sichere "
            "Querungshilfen prüfen."
        ),
        summary_en=(
            f"{n} accidents involving cyclists or pedestrians "
            f"({n_severe} serious or fatal). Evaluate segregated cycling infrastructure "
            "and safe crossing facilities."
        ),
        description_de_md=(
            "## Befund\n"
            f"**{n} Unfälle** betreffen gefährdete Verkehrsteilnehmer:innen "
            f"(Radfahrende, Fußgänger:innen), davon **{n_severe} schwer oder tödlich**.\n\n"
            "## Vorschlag\n"
            "- Physisch geschützte Radspuren oder Radwege anlegen\n"
            "- Sichere, gut beleuchtete Querungsmöglichkeiten schaffen\n"
            "- Tempo-30-Zonen in betroffenen Abschnitten prüfen\n"
            "- Sichtachsen an Kreuzungen freistellen (parkende Fahrzeuge)"
        ),
        description_en_md=(
            "## Finding\n"
            f"**{n} accidents** involve vulnerable road users "
            f"(cyclists, pedestrians), of which **{n_severe} are serious or fatal**.\n\n"
            "## Proposal\n"
            "- Install physically protected cycle lanes or paths\n"
            "- Provide safe, well-lit crossing facilities\n"
            "- Evaluate 30 km/h zones on affected sections\n"
            "- Clear sight lines at junctions (remove parked vehicles)"
        ),
        effort_level="medium",
        evidence={
            "vru_accident_count": n,
            "vru_severe_count": n_severe,
        },
        scores={
            "climate": score(0.35, "low"),
            "safety": score(
                safety_val,
                "high",
                "Schutz der schwächsten Verkehrsteilnehmer:innen.",
                "Protecting the most vulnerable road users.",
            ),
            "quality_of_life": score(0.7, "medium"),
            "social": score(0.8, "high"),
            "feasibility": score(0.55, "medium"),
            "cost": score(0.45, "medium"),
            "visibility": score(0.8, "high"),
            "political": score(0.8, "high"),
            "goal_alignment": score(0.85, "high"),
        },
    )
