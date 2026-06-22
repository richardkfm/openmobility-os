"""Workspace-scoped views: dashboard, map, data hub, measures, methodology."""

from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from core.utils import get_active_workspace
from datasets.models import DataSource, MobilitySnapshot, NormalizedFeatureSet
from datasets.readiness import (
    layer_provenance_map,
    source_provenance,
    workspace_data_basis,
)
from measures.accident_kpis import compute_accident_kpis
from measures.models import Measure, MeasureScore
from measures.scoring import compute_priority_score
from measures.transit_kpis import compute_transit_kpis


def dashboard(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    goals = ws.goals.all()
    measures = list(ws.measures.prefetch_related("scores").all())
    ranked = sorted(
        measures, key=lambda m: compute_priority_score(m, ws.scoring_weights), reverse=True
    )[:5]
    sources = ws.data_sources.all()
    feature_sets = NormalizedFeatureSet.objects.filter(workspace=ws)
    transit_kpis = compute_transit_kpis(ws, feature_sets)
    accident_kpis = compute_accident_kpis(ws, feature_sets)
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
            "data_basis": workspace_data_basis(ws),
            "transit_kpis": transit_kpis,
            "accident_kpis": accident_kpis,
            "page_title": ws.name,
        },
    )


def workspace_map(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    # Only include layer kinds from *enabled* sources so the checkbox panel
    # stays in sync with what the map API will actually return.
    feature_sets = NormalizedFeatureSet.objects.filter(workspace=ws, source__is_enabled=True)
    kind_values = list(feature_sets.values_list("layer_kind", flat=True).distinct())

    # Map every kind to its translated LayerKind label; fall back to the raw
    # value (with underscores replaced) for connector-defined kinds that aren't
    # in the enum.
    label_map = dict(DataSource.LayerKind.choices)
    provenance_by_kind = layer_provenance_map(ws)
    layers = [
        {
            "value": v,
            "label": str(label_map.get(v, v.replace("_", " ").capitalize())),
            "provenance": provenance_by_kind.get(v),
        }
        for v in sorted(kind_values)
    ]

    # The "Density lines" accident view snaps points onto a street network, so
    # it is only offered when the workspace has actually synced one.
    has_streets = any(k in kind_values for k in ("streets_with_speed", "streets"))

    # Cycling gap analysis preset needs accidents + at least one cycling layer.
    has_cycling_gap_data = "accidents" in kind_values and any(
        k in kind_values for k in ("dedicated_bike_network", "cycling_counts")
    )
    # "Safe routes to school" story view overlays school locations with the
    # accident record — it only makes sense when both are present.
    has_safe_school_data = "schools" in kind_values and "accidents" in kind_values
    # "Traffic safety overview" snaps accidents onto the speed-limited street
    # network, so it needs both an accidents layer and a streets layer.
    has_traffic_safety_data = "accidents" in kind_values and any(
        k in kind_values for k in ("streets_with_speed", "streets")
    )
    # "Urban heat & shade" contrasts sealed (heat-trapping) surfaces with the
    # green cover that offsets them — it needs the sealed layer plus at least
    # one cooling/heat layer.
    has_urban_heat_data = "sealed_surfaces" in kind_values and any(
        k in kind_values for k in ("green_areas", "trees", "heat_corridors")
    )
    # "Flood & water resilience" needs at least one blue/hazard layer to read.
    has_flood_water_data = any(
        k in kind_values for k in ("water_bodies", "flood_risk")
    )
    # "Cooling green network" maps the network of cool refuges, so it needs
    # green areas plus at least one other cooling layer to be worth showing.
    has_cooling_green_data = "green_areas" in kind_values and any(
        k in kind_values for k in ("trees", "heat_corridors")
    )
    has_districts = ws.districts.exists()

    # Shared-mobility availability gap overlay — only offered when snapshots
    # have actually been collected (otherwise the grid is empty). Lists the
    # sources that have a history so the operator can pick which fleet to view.
    gap_source_ids = (
        MobilitySnapshot.objects.filter(workspace=ws)
        .values_list("source_id", flat=True)
        .distinct()
    )
    mobility_gap_sources = [
        {"id": s.pk, "name": s.name}
        for s in DataSource.objects.filter(pk__in=list(gap_source_ids)).order_by("name")
    ]

    response = render(
        request,
        "workspaces/map.html",
        {
            "workspace": ws,
            "layers": layers,
            "layer_kinds": kind_values,
            "mobility_gap_sources": mobility_gap_sources,
            "has_streets": has_streets,
            "has_cycling_gap_data": has_cycling_gap_data,
            "has_safe_school_data": has_safe_school_data,
            "has_traffic_safety_data": has_traffic_safety_data,
            "has_urban_heat_data": has_urban_heat_data,
            "has_flood_water_data": has_flood_water_data,
            "has_cooling_green_data": has_cooling_green_data,
            "has_districts": has_districts,
            "measure_categories": Measure.Category.choices,
            "page_title": _("Map — %(name)s") % {"name": ws.name},
        },
    )
    # Tile providers (notably the OpenStreetMap volunteer servers) reject
    # cross-origin requests that arrive without a Referer header. Django's
    # default Referrer-Policy is "same-origin", which strips the Referer on
    # cross-origin tile fetches. Send the origin only (no path or query) on
    # cross-origin requests so the policy check passes without leaking the
    # workspace URL to the tile provider.
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def measures_list(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    strategy = request.GET.get("strategy", "default")
    category = request.GET.get("category", "")
    effort = request.GET.get("effort", "")

    qs = Measure.objects.filter(workspace=ws).prefetch_related("scores")
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
    ws = get_active_workspace(workspace_slug)
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
    ws = get_active_workspace(workspace_slug)
    sources = ws.data_sources.all()
    data_sources_with_meta = [(s, source_provenance(s)) for s in sources]
    return render(
        request,
        "workspaces/methodology.html",
        {
            "workspace": ws,
            "data_sources": sources,
            "data_sources_with_meta": data_sources_with_meta,
            "data_basis": workspace_data_basis(ws),
            "scoring_weights": ws.scoring_weights or {},
            "page_title": _("Methodology — %(name)s") % {"name": ws.name},
        },
    )


STRATEGY_OVERRIDES = {
    "quick_wins": {"feasibility": 3.0, "cost": 2.0},
    "vision_zero": {"safety": 3.0, "social": 1.5},
    "max_climate": {"climate": 3.0, "goal_alignment": 2.0},
    "fair_distribution": {"social": 2.0, "quality_of_life": 2.0},
}


def _strategy_weights(strategy: str, base_weights: dict) -> dict:
    """Overlay a strategy preset onto the workspace's base dimension weights."""
    from measures.scoring import DEFAULT_WEIGHTS

    base = {**DEFAULT_WEIGHTS, **(base_weights or {})}
    return {**base, **STRATEGY_OVERRIDES.get(strategy, {})}
