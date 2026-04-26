"""GeoJSON feature API consumed by MapLibre on the workspace map page."""

import json

from django.http import JsonResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from core.utils import get_active_workspace
from datasets.models import NormalizedFeatureSet


@require_GET
@cache_page(30)
def workspace_layer(request, workspace_slug: str, layer_kind: str):
    ws = get_active_workspace(workspace_slug)
    # Multiple data sources can publish into the same layer kind (e.g. one
    # Unfallatlas datasource per year). Aggregate across all feature sets so
    # the map sees a single FeatureCollection per layer.
    feature_sets = NormalizedFeatureSet.objects.filter(workspace=ws, layer_kind=layer_kind)
    features: list = []
    for fs in feature_sets:
        fc = fs.feature_collection or {}
        features.extend(fc.get("features") or [])
    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
def workspace_measures_geojson(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    features = []
    for m in ws.measures.exclude(geometry__isnull=True):
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(m.geometry.geojson),
                "properties": {
                    "slug": m.slug,
                    "title": m.title_de,
                    "category": m.category,
                    "effort_level": m.effort_level,
                    "status": m.status,
                },
            }
        )
    return JsonResponse({"type": "FeatureCollection", "features": features})
