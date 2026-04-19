"""Workspace-scoped views: dashboard, map, data hub, measures, methodology."""

from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from datasets.models import DataSource, NormalizedFeatureSet
from goals.models import WorkspaceGoal
from measures.models import Measure, MeasureScore
from measures.scoring import compute_priority_score

from .models import Workspace


def _get_workspace(slug: str) -> Workspace:
    return get_object_or_404(Workspace, slug=slug, is_active=True)


def dashboard(request, workspace_slug: str):
    ws = _get_workspace(workspace_slug)
    goals = ws.goals.all()
    measures = list(ws.measures.all())
    ranked = sorted(
        measures, key=lambda m: compute_priority_score(m, ws.scoring_weights), reverse=True
    )[:5]
    sources = ws.data_sources.all()
    return render(
        request,
        "workspaces/dashboard.html",
        {
            "workspace": ws,
            "goals": goals,
            "top_measures": ranked,
            "measure_count": len(measures),
            "data_source_count": sources.count(),
            "data_sources_active": sources.filter(status=DataSource.Status.ACTIVE).count(),
            "page_title": ws.name,
        },
    )


def workspace_map(request, workspace_slug: str):
    ws = _get_workspace(workspace_slug)
    feature_sets = NormalizedFeatureSet.objects.filter(workspace=ws)
    layer_kinds = list(feature_sets.values_list("layer_kind", flat=True).distinct())
    return render(
        request,
        "workspaces/map.html",
        {
            "workspace": ws,
            "layer_kinds": layer_kinds,
            "page_title": _("Map — %(name)s") % {"name": ws.name},
        },
    )


def measures_list(request, workspace_slug: str):
    ws = _get_workspace(workspace_slug)
    strategy = request.GET.get("strategy", "default")
    category = request.GET.get("category", "")
    effort = request.GET.get("effort", "")

    qs = Measure.objects.filter(workspace=ws)
    if category:
        qs = qs.filter(category=category)
    if effort:
        qs = qs.filter(effort_level=effort)

    measures = list(qs)
    weights = _strategy_weights(strategy, ws.scoring_weights)
    ranked = sorted(
        measures, key=lambda m: compute_priority_score(m, weights), reverse=True
    )

    context = {
        "workspace": ws,
        "measures": ranked,
        "strategy": strategy,
        "category": category,
        "effort": effort,
        "categories": Measure.Category.choices,
        "efforts": Measure.EffortLevel.choices,
        "strategies": [
            ("default", _("Default weighting")),
            ("quick_wins", _("Quick Wins")),
            ("vision_zero", _("Vision Zero")),
            ("max_climate", _("Maximum climate impact")),
            ("fair_distribution", _("Fair citywide distribution")),
        ],
        "page_title": _("Measures — %(name)s") % {"name": ws.name},
    }

    template = "workspaces/_measures_list.html" if request.htmx else "workspaces/measures.html"
    return render(request, template, context)


def measure_detail(request, workspace_slug: str, measure_slug: str):
    ws = _get_workspace(workspace_slug)
    measure = get_object_or_404(Measure, workspace=ws, slug=measure_slug)
    scores = measure.scores.all()
    priority = compute_priority_score(measure, ws.scoring_weights)
    return render(
        request,
        "workspaces/measure_detail.html",
        {
            "workspace": ws,
            "measure": measure,
            "scores": scores,
            "priority_score": priority,
            "dimension_choices": dict(MeasureScore.Dimension.choices),
            "page_title": measure.title_localized(request.LANGUAGE_CODE),
        },
    )


def workspace_methodology(request, workspace_slug: str):
    ws = _get_workspace(workspace_slug)
    return render(
        request,
        "workspaces/methodology.html",
        {
            "workspace": ws,
            "data_sources": ws.data_sources.all(),
            "scoring_weights": ws.scoring_weights or {},
            "page_title": _("Methodology — %(name)s") % {"name": ws.name},
        },
    )


def _strategy_weights(strategy: str, base_weights: dict) -> dict:
    """Map a strategy preset onto dimension weights."""
    from measures.scoring import DEFAULT_WEIGHTS

    base = {**DEFAULT_WEIGHTS, **(base_weights or {})}
    if strategy == "quick_wins":
        return {**base, "feasibility": 3.0, "cost": 2.0}
    if strategy == "vision_zero":
        return {**base, "safety": 3.0, "social": 1.5}
    if strategy == "max_climate":
        return {**base, "climate": 3.0, "goal_alignment": 2.0}
    if strategy == "fair_distribution":
        return {**base, "social": 2.0, "quality_of_life": 2.0}
    return base
