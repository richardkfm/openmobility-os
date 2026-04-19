"""Public JSON API for programmatic consumption of OpenMobility OS data."""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from workspaces.models import Workspace


@require_GET
def meta_view(request):
    return JsonResponse(
        {
            "platform": "OpenMobility OS",
            "version": settings.PLATFORM_VERSION,
            "deployment_mode": settings.DEPLOYMENT_MODE,
            "workspaces_count": Workspace.objects.filter(is_active=True).count(),
        }
    )


@require_GET
def workspace_list(request):
    data = [
        {
            "slug": w.slug,
            "name": w.name,
            "country_code": w.country_code,
            "kind": w.kind,
            "is_demo": w.is_demo,
            "population": w.population,
        }
        for w in Workspace.objects.filter(is_active=True)
    ]
    return JsonResponse({"results": data, "count": len(data)})


@require_GET
def workspace_detail(request, slug):
    w = get_object_or_404(Workspace, slug=slug, is_active=True)
    return JsonResponse(
        {
            "slug": w.slug,
            "name": w.name,
            "country_code": w.country_code,
            "region": w.region,
            "kind": w.kind,
            "language_code": w.language_code,
            "timezone": w.timezone,
            "population": w.population,
            "area_km2": float(w.area_km2) if w.area_km2 else None,
            "is_demo": w.is_demo,
            "description_de": w.description_de,
            "description_en": w.description_en,
            "default_zoom": w.default_zoom,
            "center": (
                [w.center.x, w.center.y] if w.center else None
            ),
            "bounds": list(w.bounds.extent) if w.bounds else None,
            "goals_count": w.goals.count(),
            "measures_count": w.measures.count(),
            "data_sources_count": w.data_sources.count(),
        }
    )


@require_GET
def measures_list(request, slug):
    w = get_object_or_404(Workspace, slug=slug, is_active=True)
    data = [
        {
            "slug": m.slug,
            "title_de": m.title_de,
            "title_en": m.title_en,
            "category": m.category,
            "effort_level": m.effort_level,
            "status": m.status,
            "url": f"/{w.slug}/measures/{m.slug}/",
        }
        for m in w.measures.all()
    ]
    return JsonResponse({"results": data, "count": len(data)})
