"""Workspace- and area-level policy goals and KPI targets."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .indicators import get_indicator, is_vision_zero


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


class AreaTarget(models.Model):
    """A measurable goal attached to one focus area.

    The ethical rule of this model is :meth:`clean`: an indicator that counts
    people killed or seriously injured can only carry a target of zero. A
    percentage target on such an indicator would state, as project scope, that
    some number of deaths is acceptable. That is not a target OpenMobility OS
    will store, render, or report progress against, so it is rejected at the
    model layer rather than merely discouraged in the UI.
    """

    class TargetMode(models.TextChoices):
        ZERO = "zero", _("Zero — no one killed or seriously injured")
        ABSOLUTE = "absolute", _("Absolute value")
        PERCENT = "percent", _("Percentage change")

    class Direction(models.TextChoices):
        DECREASE = "decrease", _("Lower is better")
        INCREASE = "increase", _("Higher is better")

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="area_targets"
    )
    focus_area = models.ForeignKey(
        "workspaces.FocusArea", on_delete=models.CASCADE, related_name="targets"
    )
    code = models.SlugField(max_length=100)

    indicator = models.CharField(
        max_length=60,
        help_text=_("Key from the indicator catalogue (goals/indicators.py)."),
    )
    target_mode = models.CharField(
        max_length=20, choices=TargetMode.choices, default=TargetMode.ZERO
    )
    direction = models.CharField(
        max_length=20, choices=Direction.choices, default=Direction.DECREASE
    )

    baseline_value = models.FloatField(null=True, blank=True)
    baseline_meta = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("How the baseline was computed — years, counts, filters."),
    )

    target_value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    deadline_year = models.PositiveSmallIntegerField(null=True, blank=True)

    workspace_goal = models.ForeignKey(
        "goals.WorkspaceGoal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="area_targets",
        help_text=_("City-wide goal this area target contributes to."),
    )

    rationale_de = models.TextField(blank=True)
    rationale_en = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("focus_area", "code")]
        ordering = ["focus_area", "code"]

    def __str__(self):
        return f"{self.focus_area.slug}/{self.code}"

    def clean(self):
        spec = get_indicator(self.indicator)
        if spec is None:
            raise ValidationError({"indicator": _("Unknown indicator.")})

        if is_vision_zero(self.indicator):
            if self.target_mode != self.TargetMode.ZERO:
                raise ValidationError(
                    {
                        "target_mode": _(
                            "Targets for people killed or seriously injured must be "
                            "zero. A percentage or residual target would declare a "
                            "number of deaths acceptable."
                        )
                    }
                )
            if self.target_value not in (None, 0):
                raise ValidationError(
                    {"target_value": _("This target can only be zero.")}
                )
            self.target_value = 0
        elif self.target_mode == self.TargetMode.ZERO:
            # Zero is always allowed as an ambition, even where not required.
            self.target_value = 0

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)

    @property
    def is_vision_zero(self) -> bool:
        return is_vision_zero(self.indicator)

    def rationale_for(self, language_code: str) -> str:
        if str(language_code).startswith("en") and self.rationale_en:
            return self.rationale_en
        return self.rationale_de
