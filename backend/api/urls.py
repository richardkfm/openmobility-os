"""Public read-only API."""

from django.urls import path

from maps.views import workspace_layer, workspace_measures_geojson

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
        "workspaces/<slug:workspace_slug>/measures.geojson",
        workspace_measures_geojson,
        name="api_workspace_measures_geojson",
    ),
]
