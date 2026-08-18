"""Focus areas and their targets — list, detail, and the admin write actions.

Read access is public, per the open-public-layer principle: anyone can inspect
an area plan, its assumptions and its residual harm without an account. Creating
areas, generating plans and deleting them require the shared admin token.
"""

from django.contrib import messages
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.contrib.gis.geos.error import GEOSException
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from core.utils import get_active_workspace
from datasets.models import NormalizedFeatureSet
from goals.indicators import (
    INDICATORS,
    available_indicators,
    is_vision_zero,
    label_for,
    unit_for,
)
from goals.models import AreaTarget
from measures.area_engine import build_area_plan
from measures.effects import factors_for

from .models import FocusArea


def _area_or_404(ws, area_slug):
    try:
        return FocusArea.objects.get(workspace=ws, slug=area_slug)
    except FocusArea.DoesNotExist as exc:
        raise Http404("No such focus area in this workspace") from exc


def areas_list(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    lang = getattr(request, "LANGUAGE_CODE", "de")

    rows = []
    for area in ws.focus_areas.prefetch_related("targets__plans"):
        target = area.current_target
        plan = target.plans.first() if target else None
        rows.append(
            {
                "area": area,
                "target": target,
                "plan": plan,
                "indicator_label": label_for(target.indicator, lang) if target else "",
                "unit": unit_for(target.indicator, lang) if target else "",
            }
        )

    return render(
        request,
        "workspaces/areas.html",
        {
            "workspace": ws,
            "rows": rows,
            "indicators": area_indicator_options(ws, lang),
        },
    )


def area_detail(request, workspace_slug, area_slug):
    ws = get_active_workspace(workspace_slug)
    area = _area_or_404(ws, area_slug)
    lang = getattr(request, "LANGUAGE_CODE", "de")

    target = area.current_target
    plan = target.plans.first() if target else None
    items = (
        plan.items.select_related("measure").order_by("rank") if plan else []
    )

    # Cumulative projection, so the page can show how far down the ranked list
    # the target is reached — and, for a Vision Zero target, that it is not.
    cumulative = []
    if plan and target:
        baseline = (plan.projection or {}).get("baseline") or 0.0
        running = 0.0
        for item in items:
            running += item.affected_baseline * item.effect_central
            cumulative.append(
                {
                    "rank": item.rank,
                    "remaining": round(baseline * (1 - min(running, 1.0)), 2),
                    "pct": round(min(running, 1.0) * 100, 1),
                }
            )

    return render(
        request,
        "workspaces/area_detail.html",
        {
            "workspace": ws,
            "area": area,
            "target": target,
            "plan": plan,
            "items": items,
            "cumulative": cumulative,
            "indicator_label": label_for(target.indicator, lang) if target else "",
            "unit": unit_for(target.indicator, lang) if target else "",
            "is_vision_zero": target.is_vision_zero if target else False,
            "effect_factors": factors_for(ws),
        },
    )


def area_indicator_options(ws, lang):
    """Indicators this workspace can actually measure, for the target form."""
    kinds = set(
        NormalizedFeatureSet.objects.filter(
            workspace=ws, source__is_enabled=True
        ).values_list("layer_kind", flat=True)
    )
    return [
        {
            "key": key,
            "label": label_for(key, lang),
            "unit": unit_for(key, lang),
            "vision_zero": is_vision_zero(key),
        }
        for key in available_indicators(kinds)
    ]


@admin_required
@require_POST
def area_create(request, workspace_slug):
    """Create a focus area plus its first target, then build the plan.

    The geometry arrives as GeoJSON from the map's drawing tool or from a
    polygon the user adopted off an existing layer.
    """
    ws = get_active_workspace(workspace_slug)
    name = (request.POST.get("name") or "").strip()
    raw_geometry = request.POST.get("geometry") or ""
    indicator = (request.POST.get("indicator") or "").strip()

    if not name or not raw_geometry or indicator not in INDICATORS:
        messages.error(request, _("Name, area geometry, and indicator are required."))
        return redirect(reverse("areas_list", kwargs={"workspace_slug": ws.slug}))

    try:
        geom = GEOSGeometry(raw_geometry, srid=4326)
    except (ValueError, TypeError, GEOSException):
        messages.error(request, _("The area geometry could not be read."))
        return redirect(reverse("areas_list", kwargs={"workspace_slug": ws.slug}))

    if geom.geom_type == "Polygon":
        geom = MultiPolygon(geom, srid=4326)
    elif geom.geom_type != "MultiPolygon":
        messages.error(request, _("A focus area must be a polygon."))
        return redirect(reverse("areas_list", kwargs={"workspace_slug": ws.slug}))

    slug = _unique_slug(ws, name)
    origin = request.POST.get("origin") or FocusArea.Origin.DRAWN

    vision_zero = is_vision_zero(indicator)
    target_mode = (
        AreaTarget.TargetMode.ZERO
        if vision_zero
        else (request.POST.get("target_mode") or AreaTarget.TargetMode.ABSOLUTE)
    )
    target_value = 0 if vision_zero else _to_float(request.POST.get("target_value"))

    try:
        with transaction.atomic():
            area = FocusArea.objects.create(
                workspace=ws,
                slug=slug,
                name=name,
                geometry=geom,
                origin=origin,
                origin_ref=(request.POST.get("origin_ref") or "")[:300],
            )
            target = AreaTarget(
                workspace=ws,
                focus_area=area,
                code="primary",
                indicator=indicator,
                target_mode=target_mode,
                target_value=target_value,
                unit=unit_for(indicator, getattr(request, "LANGUAGE_CODE", "de")),
                deadline_year=_to_int(request.POST.get("deadline_year")),
            )
            target.save()
            build_area_plan(target)
    except ValidationError as exc:
        messages.error(request, "; ".join(_flatten(exc)))
        return redirect(reverse("areas_list", kwargs={"workspace_slug": ws.slug}))

    messages.success(request, _("Focus area created and plan generated."))
    return redirect(
        reverse("area_detail", kwargs={"workspace_slug": ws.slug, "area_slug": slug})
    )


@admin_required
@require_POST
def area_generate_plan(request, workspace_slug, area_slug):
    ws = get_active_workspace(workspace_slug)
    area = _area_or_404(ws, area_slug)
    target = area.current_target
    if target is None:
        messages.error(request, _("This area has no target to plan against."))
    else:
        plan = build_area_plan(target)
        messages.success(
            request,
            _("Plan rebuilt: %(n)d segments.") % {"n": plan.items.count()},
        )
    return redirect(
        reverse("area_detail", kwargs={"workspace_slug": ws.slug, "area_slug": area_slug})
    )


@admin_required
@require_POST
def area_delete(request, workspace_slug, area_slug):
    ws = get_active_workspace(workspace_slug)
    area = _area_or_404(ws, area_slug)
    area.delete()
    messages.success(request, _("Focus area deleted."))
    return redirect(reverse("areas_list", kwargs={"workspace_slug": ws.slug}))


def _unique_slug(ws, name):
    base = slugify(name)[:90] or "area"
    slug, n = base, 2
    while FocusArea.objects.filter(workspace=ws, slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _to_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flatten(exc):
    for field, errors in (getattr(exc, "message_dict", None) or {}).items():
        for error in errors:
            yield f"{field}: {error}"
