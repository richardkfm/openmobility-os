"""GeoJSON feature API consumed by MapLibre on the workspace map page."""

import json

from django.http import JsonResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from core.utils import get_active_workspace
from datasets.models import NormalizedFeatureSet
from measures.accident_density import compute_density_lines
from measures.models import MeasureScore
from measures.scoring import compute_priority_score


def _features_for_kind(ws, layer_kind):
    """Aggregate features across all enabled sources of a layer kind."""
    feature_sets = NormalizedFeatureSet.objects.filter(
        workspace=ws, layer_kind=layer_kind, source__is_enabled=True
    )
    features: list = []
    for fs in feature_sets:
        fc = fs.feature_collection or {}
        features.extend(fc.get("features") or [])
    return features


def _csv_param(request, name):
    """Parse a comma-separated query param into a list (empty → None)."""
    raw = (request.GET.get(name) or "").strip()
    if not raw:
        return None
    return [v.strip() for v in raw.split(",") if v.strip()]


@require_GET
@cache_page(30)
def workspace_layer(request, workspace_slug: str, layer_kind: str):
    ws = get_active_workspace(workspace_slug)
    # Multiple data sources can publish into the same layer kind (e.g. one
    # Unfallatlas datasource per year). Aggregate across all feature sets so
    # the map sees a single FeatureCollection per layer.
    # Disabled sources (is_enabled=False) are excluded from map rendering.
    features = _features_for_kind(ws, layer_kind)
    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
@cache_page(300)
def accident_density_view(request, workspace_slug: str):
    """Streets coloured by severity-weighted accident density (Unfallatlas-style).

    Snaps accident points to the workspace street network and returns one
    coloured LineString per street that received matching accidents. The
    aggregation depends on the active filters, so unlike the circle/heatmap
    layers this is recomputed server-side per filter combination (cached for
    5 minutes, keyed on the querystring). Filters: ``years``, ``severity``,
    ``modes`` — all comma-separated; empty means "all". The ``modes`` filter
    (e.g. ``cyclist``) drives the aggregation here, which is what powers the
    cycling-infrastructure-gap workflow.
    """
    ws = get_active_workspace(workspace_slug)
    accidents = _features_for_kind(ws, "accidents")
    streets = _features_for_kind(ws, "streets_with_speed") or _features_for_kind(
        ws, "streets"
    )

    center = ws.center
    center_lonlat = (center.x, center.y) if center else (0.0, 0.0)

    fc = compute_density_lines(
        accidents,
        streets,
        center_lonlat=center_lonlat,
        years=_csv_param(request, "years"),
        severities=_csv_param(request, "severity"),
        modes=_csv_param(request, "modes"),
    )
    return JsonResponse(fc)


@require_GET
def workspace_measures_geojson(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    lang = getattr(request, "LANGUAGE_CODE", "de")
    weights = ws.scoring_weights or {}
    features = []
    for m in ws.measures.exclude(geometry__isnull=True).prefetch_related("scores"):
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(m.geometry.geojson),
                "properties": {
                    "slug": m.slug,
                    "title": m.title_localized(lang),
                    "summary": m.summary_localized(lang),
                    "category": m.category,
                    "effort_level": m.effort_level,
                    "status": m.status,
                    "priority_score": compute_priority_score(m, weights),
                },
            }
        )
    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
@cache_page(60)
def district_scores_view(request, workspace_slug: str):
    """Districts coloured by aggregate measure priority.

    The ``dimension`` query parameter selects a single scoring dimension
    (e.g. ``safety``, ``climate``). Omit it or pass an unknown value to use
    the workspace-weighted overall priority score.
    """
    ws = get_active_workspace(workspace_slug)
    dimension = (request.GET.get("dimension") or "").strip()
    valid_dims = {d for d, _ in MeasureScore.Dimension.choices}
    if dimension not in valid_dims:
        dimension = ""

    weights = ws.scoring_weights or {}
    features = []

    for district in ws.districts.all():
        if district.geometry is None:
            continue

        measures = list(district.measures.prefetch_related("scores").all())

        if not measures:
            score = 0.0
            measure_count = 0
        elif dimension:
            vals = []
            for m in measures:
                for s in m.scores.all():
                    if s.dimension == dimension:
                        vals.append(s.display_value)
                        break
            score = round(sum(vals) / len(vals), 1) if vals else 0.0
            measure_count = len(measures)
        else:
            scores_list = [compute_priority_score(m, weights) for m in measures]
            score = round(sum(scores_list) / len(scores_list), 1) if scores_list else 0.0
            measure_count = len(measures)

        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(district.geometry.geojson),
                "properties": {
                    "district_name": district.name,
                    "score": score,
                    "measure_count": measure_count,
                },
            }
        )

    return JsonResponse({"type": "FeatureCollection", "features": features})
