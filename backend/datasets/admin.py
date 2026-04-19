from django.contrib import admin

from .models import DataSource, NormalizedFeatureSet


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "source_type", "layer_kind", "status", "last_synced_at")
    list_filter = ("status", "source_type", "layer_kind", "workspace")
    search_fields = ("name",)


@admin.register(NormalizedFeatureSet)
class NormalizedFeatureSetAdmin(admin.ModelAdmin):
    list_display = ("workspace", "layer_kind", "record_count", "synced_at")
    list_filter = ("workspace", "layer_kind")
