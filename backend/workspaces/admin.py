from django.contrib import admin

from .models import District, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "country_code", "kind", "is_demo", "is_active")
    list_filter = ("is_demo", "is_active", "kind", "country_code")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "slug")
    list_filter = ("workspace",)
    search_fields = ("name",)
