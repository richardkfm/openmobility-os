"""Rule: population-equity gap.

Reads the ``population_grid`` layer (Zensus 2022 100 m cells) and identifies
concentrations of vulnerable populations (children <18, elderly ≥65) that
are materially above the workspace average. When such clusters exist, the
rule generates a measure recommending that infrastructure investment be
directed toward those areas — the core "this measure serves X residents,
Y % of whom are children" evidence line.

Consumed layer kind: ``population_grid``
Expected feature properties (flexible naming via ``population_column``,
``under_18_column``, ``over_65_column`` — with sensible defaults):
- total population per cell
- population under 18 per cell
- population 65 and older per cell
"""

from ._common import MeasureCandidate, score, select_by_layer


DEFAULT_POP_COLUMN = "Einwohner"
DEFAULT_UNDER_18_COLUMN = "Alter_unter_18"
DEFAULT_OVER_65_COLUMN = "Alter_65_und_aelter"

CLUSTER_THRESHOLD_FACTOR = 1.5
MIN_CELLS_FOR_RULE = 10


def rule_population_equity_gap(workspace, feature_sets):
    grid_fs = select_by_layer(feature_sets, "population_grid")
    if not grid_fs:
        return []

    features = grid_fs.feature_collection.get("features", [])
    if len(features) < MIN_CELLS_FOR_RULE:
        return []

    pop_col = DEFAULT_POP_COLUMN
    u18_col = DEFAULT_UNDER_18_COLUMN
    o65_col = DEFAULT_OVER_65_COLUMN

    total_pop = 0
    total_u18 = 0
    total_o65 = 0
    cells_with_data = 0

    for f in features:
        props = f.get("properties") or {}
        pop = _int_or_zero(props.get(pop_col))
        u18 = _int_or_zero(props.get(u18_col))
        o65 = _int_or_zero(props.get(o65_col))
        if pop > 0:
            total_pop += pop
            total_u18 += u18
            total_o65 += o65
            cells_with_data += 1

    if cells_with_data < MIN_CELLS_FOR_RULE or total_pop == 0:
        return []

    avg_u18_share = total_u18 / total_pop
    avg_o65_share = total_o65 / total_pop

    high_child_cells = 0
    high_elderly_cells = 0
    pop_in_child_clusters = 0
    pop_in_elderly_clusters = 0

    for f in features:
        props = f.get("properties") or {}
        pop = _int_or_zero(props.get(pop_col))
        if pop <= 0:
            continue
        u18 = _int_or_zero(props.get(u18_col))
        o65 = _int_or_zero(props.get(o65_col))
        cell_u18_share = u18 / pop
        cell_o65_share = o65 / pop

        if cell_u18_share > avg_u18_share * CLUSTER_THRESHOLD_FACTOR:
            high_child_cells += 1
            pop_in_child_clusters += pop
        if cell_o65_share > avg_o65_share * CLUSTER_THRESHOLD_FACTOR:
            high_elderly_cells += 1
            pop_in_elderly_clusters += pop

    cluster_cells = high_child_cells + high_elderly_cells
    cluster_pct = cluster_cells / (cells_with_data * 2) * 100

    if cluster_pct < 5:
        return []

    pop_affected = pop_in_child_clusters + pop_in_elderly_clusters
    pop_affected_unique = min(pop_affected, total_pop)

    social_val = min(0.95, 0.6 + cluster_pct / 100)

    return [
        MeasureCandidate(
            slug="equity-focused-infrastructure",
            category="other",
            title_de="Infrastruktur-Investition in unterversorgte Quartiere mit hohem Anteil vulnerabler Bevölkerung",
            title_en="Infrastructure investment in under-served areas with high vulnerable-population share",
            summary_de=(
                f"Bevölkerungsraster: {cells_with_data} bewohnte Zellen erfasst, "
                f"{total_pop:,} Einwohner:innen gesamt. "
                f"{high_child_cells} Zellen mit überdurchschnittlichem Kinderanteil "
                f"({pop_in_child_clusters:,} Einw.), "
                f"{high_elderly_cells} Zellen mit überdurchschnittlichem Seniorenanteil "
                f"({pop_in_elderly_clusters:,} Einw.)."
            ),
            summary_en=(
                f"Population grid: {cells_with_data} populated cells, "
                f"{total_pop:,} residents total. "
                f"{high_child_cells} cells with above-average child share "
                f"({pop_in_child_clusters:,} res.), "
                f"{high_elderly_cells} cells with above-average elderly share "
                f"({pop_in_elderly_clusters:,} res.)."
            ),
            description_de_md=(
                "## Befund\n"
                f"Das Bevölkerungsraster (Zensus 2022, 100 m) umfasst **{cells_with_data} "
                f"bewohnte Zellen** mit insgesamt **{total_pop:,} Einwohner:innen** "
                f"im Workspace **{workspace.name}**.\n\n"
                f"- Durchschnittlicher Anteil unter 18: **{avg_u18_share * 100:.1f} %**\n"
                f"- Durchschnittlicher Anteil 65+: **{avg_o65_share * 100:.1f} %**\n\n"
                f"**{high_child_cells} Zellen** liegen beim Kinderanteil mindestens 50 % "
                f"über dem Durchschnitt ({pop_in_child_clusters:,} Einw.). "
                f"**{high_elderly_cells} Zellen** liegen beim Seniorenanteil mindestens "
                f"50 % über dem Durchschnitt ({pop_in_elderly_clusters:,} Einw.).\n\n"
                "## Vorschlag\n"
                "Mobilitätsmaßnahmen in diesen Quartieren priorisieren: barrierefreie "
                "Haltestellen, sichere Schulwege, Tempo-30-Zonen, belebte Gehwege. "
                "Jede Maßnahme in diesen Clustern erreicht überproportional viele "
                "vulnerable Personen pro eingesetztem Euro.\n\n"
                "## Methodik\n"
                "Zensus-2022-Gitterzellen (100 m Auflösung). Eine Zelle wird als "
                "'Cluster' gewertet, wenn der Anteil unter 18 bzw. 65+ mindestens "
                "50 % über dem Workspace-Durchschnitt liegt."
            ),
            description_en_md=(
                "## Finding\n"
                f"The population grid (Zensus 2022, 100 m) covers **{cells_with_data} "
                f"populated cells** totalling **{total_pop:,} residents** in workspace "
                f"**{workspace.name}**.\n\n"
                f"- Average share under 18: **{avg_u18_share * 100:.1f} %**\n"
                f"- Average share 65+: **{avg_o65_share * 100:.1f} %**\n\n"
                f"**{high_child_cells} cells** have a child share ≥50 % above the "
                f"workspace average ({pop_in_child_clusters:,} residents). "
                f"**{high_elderly_cells} cells** have an elderly share ≥50 % above "
                f"the average ({pop_in_elderly_clusters:,} residents).\n\n"
                "## Proposal\n"
                "Prioritize mobility measures in these areas: barrier-free transit "
                "stops, safe school routes, 30 km/h zones, and lively footpaths. "
                "Any measure placed in these clusters reaches disproportionately "
                "many vulnerable people per euro spent.\n\n"
                "## Methodology\n"
                "Zensus 2022 grid cells (100 m). A cell counts as a 'cluster' when "
                "the under-18 or 65+ share exceeds the workspace average by ≥50 %."
            ),
            effort_level="major",
            evidence={
                "cells_with_data": cells_with_data,
                "total_population": total_pop,
                "avg_under_18_share": round(avg_u18_share, 4),
                "avg_over_65_share": round(avg_o65_share, 4),
                "high_child_cells": high_child_cells,
                "high_elderly_cells": high_elderly_cells,
                "population_in_child_clusters": pop_in_child_clusters,
                "population_in_elderly_clusters": pop_in_elderly_clusters,
                "population_affected_estimate": pop_affected_unique,
                "cluster_threshold_factor": CLUSTER_THRESHOLD_FACTOR,
            },
            scores={
                "climate": score(0.3, "low"),
                "safety": score(
                    0.6,
                    "medium",
                    "Vulnerable Bevölkerung profitiert überproportional von sicherer Infrastruktur.",
                    "Vulnerable populations benefit disproportionately from safe infrastructure.",
                ),
                "quality_of_life": score(0.75, "medium"),
                "social": score(
                    social_val,
                    "high",
                    (
                        f"Cluster mit {pop_affected_unique:,} betroffenen Einwohner:innen. "
                        "Gezielte Investition verringert Mobilitätsungleichheit."
                    ),
                    (
                        f"Clusters affecting {pop_affected_unique:,} residents. "
                        "Targeted investment reduces mobility inequality."
                    ),
                ),
                "feasibility": score(0.5, "medium"),
                "cost": score(0.4, "medium"),
                "visibility": score(0.6, "medium"),
                "political": score(
                    0.7,
                    "medium",
                    "Datengestützte Priorisierung nach sozialer Wirkung stärkt politische Legitimation.",
                    "Data-driven prioritization by social impact strengthens political legitimacy.",
                ),
                "goal_alignment": score(
                    0.8,
                    "high",
                    "Erreicht überproportional Kinder/Senior:innen — direkter Beitrag zu Vision Zero und sozialer Teilhabe.",
                    "Disproportionately reaches children/elderly — direct contribution to Vision Zero and social inclusion.",
                ),
            },
        )
    ]


def _int_or_zero(value) -> int:
    if value is None or value == "" or value == "-":
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0
