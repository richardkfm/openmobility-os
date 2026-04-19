from django.contrib import admin

from .models import Measure, MeasureScore


class MeasureScoreInline(admin.TabularInline):
    model = MeasureScore
    extra = 0


@admin.register(Measure)
class MeasureAdmin(admin.ModelAdmin):
    list_display = (
        "title_de",
        "workspace",
        "category",
        "status",
        "effort_level",
        "is_auto_generated",
    )
    list_filter = ("workspace", "category", "status", "effort_level", "is_auto_generated")
    search_fields = ("title_de", "title_en", "slug")
    inlines = [MeasureScoreInline]


@admin.register(MeasureScore)
class MeasureScoreAdmin(admin.ModelAdmin):
    list_display = ("measure", "dimension", "display_value", "confidence")
    list_filter = ("dimension", "confidence")
