"""Workspace-level policy goals and KPI targets."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class WorkspaceGoal(models.Model):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="goals"
    )
    code = models.SlugField(
        max_length=100, help_text=_("Short identifier, e.g. 'modal_shift_2030'")
    )
    title_de = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200, blank=True)

    target_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True, help_text=_("e.g. %, km, t CO2"))
    deadline_year = models.PositiveSmallIntegerField(null=True, blank=True)

    rationale_de = models.TextField(blank=True)
    rationale_en = models.TextField(blank=True)

    source_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("workspace", "code")]
        ordering = ["deadline_year", "title_de"]

    def __str__(self):
        return f"{self.workspace.slug}/{self.code}"

    def title_for(self, language_code: str) -> str:
        if language_code.startswith("en") and self.title_en:
            return self.title_en
        return self.title_de

    @property
    def progress_pct(self):
        if not self.target_value or not self.current_value or self.target_value == 0:
            return None
        return round(float(self.current_value) / float(self.target_value) * 100, 1)
