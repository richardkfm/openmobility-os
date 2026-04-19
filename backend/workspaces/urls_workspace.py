"""Per-workspace URL patterns mounted under /<slug>/."""

from django.urls import path

from datasets import views as dataset_views
from measures import views as measure_views

from . import views

urlpatterns = [
    path("", views.dashboard, name="workspace_dashboard"),
    path("map/", views.workspace_map, name="workspace_map"),
    path("measures/", views.measures_list, name="measures_list"),
    path("measures/<slug:measure_slug>/", views.measure_detail, name="measure_detail"),
    path("data/", dataset_views.data_hub, name="data_hub"),
    path("data/add/", dataset_views.add_data_source, name="data_source_add"),
    path("data/<int:pk>/", dataset_views.data_source_detail, name="data_source_detail"),
    path("data/<int:pk>/sync/", dataset_views.sync_data_source, name="data_source_sync"),
    path("data/<int:pk>/test/", dataset_views.test_data_source, name="data_source_test"),
    path("data/<int:pk>/delete/", dataset_views.delete_data_source, name="data_source_delete"),
    path("methodology/", views.workspace_methodology, name="workspace_methodology"),
    path("measures/generate/", measure_views.generate_measures_view, name="measures_generate"),
]
