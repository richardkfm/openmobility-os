"""Platform-level views."""

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from workspaces.models import Workspace


def platform_landing(request):
    """Landing page — lists all workspaces, or redirects for single-city mode."""

    if settings.DEPLOYMENT_MODE == "single-city" and settings.DEFAULT_WORKSPACE_SLUG:
        return HttpResponseRedirect(
            reverse("workspace_dashboard", kwargs={"workspace_slug": settings.DEFAULT_WORKSPACE_SLUG})
        )

    workspaces = Workspace.objects.filter(is_active=True).order_by("-is_demo", "name")
    return render(
        request,
        "core/landing.html",
        {
            "workspaces": workspaces,
            "page_title": _("OpenMobility OS — Open Platform for Municipal Mobility"),
        },
    )


def about_view(request):
    return render(request, "core/about.html", {"page_title": _("About OpenMobility OS")})


def methodology_view(request):
    return render(
        request, "core/methodology.html", {"page_title": _("Methodology & Transparency")}
    )
