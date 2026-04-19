from django.contrib import admin

from .models import WorkspaceGoal


@admin.register(WorkspaceGoal)
class WorkspaceGoalAdmin(admin.ModelAdmin):
    list_display = ("title_de", "workspace", "target_value", "current_value", "deadline_year")
    list_filter = ("workspace",)
    search_fields = ("title_de", "title_en", "code")
