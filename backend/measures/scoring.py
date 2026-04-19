"""Transparent, weighted scoring for measures.

Formula:
    priority = Σ(dim_display_value_i × weight_i) / Σ(weight_i)

The default weights are documented on the methodology page. Workspaces
can override them via `Workspace.scoring_weights`.
"""

DEFAULT_WEIGHTS: dict[str, float] = {
    "climate": 1.5,
    "safety": 1.5,
    "quality_of_life": 1.2,
    "social": 1.2,
    "feasibility": 1.0,
    "cost": 1.0,
    "visibility": 0.6,
    "political": 0.8,
    "goal_alignment": 1.3,
}


def compute_priority_score(measure, workspace_weights: dict | None = None) -> float:
    weights = {**DEFAULT_WEIGHTS, **(workspace_weights or {})}
    total_w = 0.0
    total_v = 0.0
    for score in measure.scores.all():
        w = weights.get(score.dimension, 1.0)
        total_w += w
        total_v += score.display_value * w
    if total_w == 0:
        return 0.0
    return round(total_v / total_w, 1)
