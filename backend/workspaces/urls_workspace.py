"""Per-workspace URL patterns mounted under /<slug>/."""

from django.urls import path

from datasets import views as dataset_views
from measures import views as measure_views

from . import views
from . import views_admin
from . import views_export

urlpatterns = [
    path("", views.dashboard, name="workspace_dashboard"),
    path("map/", views.workspace_map, name="workspace_map"),
    path("measures/", views.measures_list, name="measures_list"),
    # NOTE: keep static measure sub-paths (e.g. generate/) above the slug
    # catch-all below, otherwise the <slug:measure_slug> pattern swallows them
    # and the request 404s as a missing measure.
    path("measures/generate/", measure_views.generate_measures_view, name="measures_generate"),
    path("measures/<slug:measure_slug>/", views.measure_detail, name="measure_detail"),
    path("data/", dataset_views.data_hub, name="data_hub"),
    path("data/add/", dataset_views.add_data_source, name="data_source_add"),
    path("data/catalog/", dataset_views.catalog_index, name="catalog_index"),
    path(
        "data/catalog/<slug:connector_id>/",
        dataset_views.catalog_browse,
        name="catalog_browse",
    ),
    path(
        "data/catalog/<slug:connector_id>/add/",
        dataset_views.catalog_add,
        name="catalog_add",
    ),
    path(
        "data/catalog/<slug:connector_id>/quickadd/",
        dataset_views.catalog_quickadd,
        name="catalog_quickadd",
    ),
    path("data/<int:pk>/", dataset_views.data_source_detail, name="data_source_detail"),
    path("data/<int:pk>/sync/", dataset_views.sync_data_source, name="data_source_sync"),
    path(
        "data/<int:pk>/snapshot/",
        dataset_views.collect_snapshot,
        name="data_source_snapshot",
    ),
    path("data/<int:pk>/test/", dataset_views.test_data_source, name="data_source_test"),
    path("data/<int:pk>/toggle/", dataset_views.toggle_data_source, name="data_source_toggle"),
    path("data/<int:pk>/delete/", dataset_views.delete_data_source, name="data_source_delete"),
    path("methodology/", views.workspace_methodology, name="workspace_methodology"),
    path("admin/health/", views_admin.HealthDashboardView.as_view(), name="workspace_health"),
    path("admin/export/", views_export.ExportView.as_view(), name="workspace_export"),
]
