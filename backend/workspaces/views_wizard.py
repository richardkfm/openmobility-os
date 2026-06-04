"""New-workspace wizard and admin authentication."""

from django.conf import settings
from django.contrib import messages
from django.contrib.gis.geos import Point, Polygon
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _

from core.decorators import admin_required
from core.middleware import SESSION_KEY

from .geocoding import GeocodingError, geocode_place
from .models import Workspace


def admin_login(request):
    """Simple token-based admin login."""
    error = None
    if request.method == "POST":
        token = request.POST.get("token", "")
        if settings.ADMIN_TOKEN and token == settings.ADMIN_TOKEN:
            request.session[SESSION_KEY] = True
            messages.success(request, _("Signed in as administrator."))
            return redirect(request.GET.get("next") or reverse("platform_landing"))
        error = _("Invalid admin token.")

    return render(
        request,
        "workspaces/admin_login.html",
        {"error": error, "page_title": _("Admin sign-in")},
    )


def admin_logout(request):
    request.session.pop(SESSION_KEY, None)
    messages.info(request, _("Signed out."))
    return redirect(reverse("platform_landing"))


@admin_required
def wizard_start(request):
    """Step 1 — basics and bounding box."""
    return render(
        request,
        "workspaces/wizard.html",
        {"page_title": _("Add a new workspace")},
    )


@admin_required
def wizard_geocode(request):
    """Resolve a place name to a bounding box so the wizard can fill it in.

    Returns JSON ``{"results": [...]}`` so the front-end can offer matches and
    auto-populate the coordinate fields. Keeps the admin from having to look up
    and type four numbers by hand.
    """
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"results": []})

    country_code = request.GET.get("country_code") or None
    try:
        results = geocode_place(query, country_code=country_code)
    except GeocodingError as exc:
        return JsonResponse(
            {"error": _("Place lookup failed: %(reason)s") % {"reason": str(exc)}},
            status=502,
        )

    return JsonResponse({"results": [r.as_dict() for r in results]})


@admin_required
def wizard_create(request):
    """Handle wizard submission — minimal validation, creates the workspace."""
    if request.method != "POST":
        return redirect(reverse("workspace_new"))

    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, _("Name is required."))
        return redirect(reverse("workspace_new"))

    slug = slugify(request.POST.get("slug") or name)[:80]
    if Workspace.objects.filter(slug=slug).exists():
        messages.error(request, _("A workspace with this slug already exists."))
        return redirect(reverse("workspace_new"))

    kind = request.POST.get("kind", Workspace.Kind.CITY)
    country_code = request.POST.get("country_code", "DE").upper()[:2]
    language_code = request.POST.get("language_code", "de")
    timezone = request.POST.get("timezone", "Europe/Berlin")

    bounds = None
    center = None
    try:
        minx = float(request.POST.get("bbox_minx", ""))
        miny = float(request.POST.get("bbox_miny", ""))
        maxx = float(request.POST.get("bbox_maxx", ""))
        maxy = float(request.POST.get("bbox_maxy", ""))
        bounds = Polygon.from_bbox((minx, miny, maxx, maxy))
        center = Point((minx + maxx) / 2, (miny + maxy) / 2, srid=4326)
    except (TypeError, ValueError):
        pass

    ws = Workspace.objects.create(
        slug=slug,
        name=name,
        kind=kind,
        country_code=country_code,
        language_code=language_code,
        timezone=timezone,
        description_de=request.POST.get("description_de", ""),
        description_en=request.POST.get("description_en", ""),
        bounds=bounds,
        center=center,
        is_demo=False,
        is_active=True,
    )

    messages.success(
        request,
        _("Workspace %(name)s created. Next step: add data sources.") % {"name": ws.name},
    )
    return redirect(reverse("data_hub", kwargs={"workspace_slug": ws.slug}))
