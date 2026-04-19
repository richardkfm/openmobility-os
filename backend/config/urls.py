"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import about_view, methodology_view, platform_landing

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/v1/", include("api.urls")),
]

urlpatterns += i18n_patterns(
    path("", platform_landing, name="platform_landing"),
    path("about/", about_view, name="about"),
    path("methodology/", methodology_view, name="methodology"),
    path("workspaces/", include("workspaces.urls_platform")),
    # Per-workspace routes are mounted last so they catch anything remaining.
    path("<slug:workspace_slug>/", include("workspaces.urls_workspace")),
    prefix_default_language=False,
)
