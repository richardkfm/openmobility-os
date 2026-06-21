"""Public read-only API."""

from django.urls import path

from maps.views import (
    accident_density_view,
    district_scores_view,
    shared_mobility_gaps_view,
    workspace_layer,
    workspace_measures_geojson,
)

from . import views

urlpatterns = [
    path("meta/", views.meta_view, name="api_meta"),
    path("workspaces/", views.workspace_list, name="api_workspace_list"),
    path("workspaces/<slug:slug>/", views.workspace_detail, name="api_workspace_detail"),
    path(
        "workspaces/<slug:slug>/measures/",
        views.measures_list,
        name="api_measures_list",
    ),
    path(
        "workspaces/<slug:workspace_slug>/features/<str:layer_kind>/",
        workspace_layer,
        name="api_workspace_layer",
    ),
    path(
        "workspaces/<slug:workspace_slug>/accident-density/",
        accident_density_view,
        name="api_accident_density",
    ),
    path(
        "workspaces/<slug:workspace_slug>/measures.geojson",
        workspace_measures_geojson,
        name="api_workspace_measures_geojson",
    ),
    path(
        "workspaces/<slug:workspace_slug>/district-scores/",
        district_scores_view,
        name="api_district_scores",
    ),
    path(
        "workspaces/<slug:workspace_slug>/shared-mobility-gaps/",
        shared_mobility_gaps_view,
        name="api_shared_mobility_gaps",
    ),
]
