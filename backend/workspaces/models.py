"""
Workspace model — represents a single city, town, municipality, region,
or administrative entity.

OpenMobility OS is city-agnostic. This model must never carry city-specific
assumptions. Any jurisdiction anywhere in the world can be a workspace.
"""

from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils.translation import gettext_lazy as _


class Workspace(models.Model):
    """A city, municipality, region, or administrative area."""

    class Kind(models.TextChoices):
        CITY = "city", _("City")
        TOWN = "town", _("Town")
        MUNICIPALITY = "municipality", _("Municipality")
        DISTRICT = "district", _("District / Neighborhood")
        COUNTY = "county", _("County / Region")
        STATE = "state", _("State / Federal State")
        OTHER = "other", _("Other")

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=200)

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CITY)
    country_code = models.CharField(
        max_length=2,
        help_text=_("ISO 3166-1 alpha-2 (e.g. DE, AT, FR, NL)"),
    )
    region = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Federal state, province, département, canton, etc."),
    )
    language_code = models.CharField(
        max_length=10,
        default="de",
        help_text=_("Default UI language for this workspace"),
    )
    timezone = models.CharField(max_length=50, default="Europe/Berlin")

    population = models.PositiveIntegerField(null=True, blank=True)
    area_km2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    description_de = models.TextField(blank=True)
    description_en = models.TextField(blank=True)

    is_demo = models.BooleanField(
        default=False,
        help_text=_("Showcase workspace — not a production deployment"),
    )
    is_active = models.BooleanField(default=True)

    bounds = gis_models.PolygonField(
        null=True,
        blank=True,
        srid=4326,
        help_text=_("Rough bounding box for map centering and Overpass queries"),
    )

    center = gis_models.PointField(
        null=True,
        blank=True,
        srid=4326,
        help_text=_("Default map center for this workspace"),
    )
    default_zoom = models.PositiveSmallIntegerField(default=12)

    scoring_weights = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Dimension → weight mapping. Defaults used if empty."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_demo", "name"]

    def __str__(self):
        return self.name

    def description_for(self, language_code: str) -> str:
        if language_code.startswith("en") and self.description_en:
            return self.description_en
        return self.description_de or self.description_en

    @property
    def display_kind(self) -> str:
        return self.get_kind_display()


class District(models.Model):
    """A named sub-area of a workspace (neighborhood, quarter, borough)."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="districts"
    )
    slug = models.SlugField(max_length=100)
    name = models.CharField(max_length=200)
    geometry = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("workspace", "slug")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.workspace.slug}/{self.name}"
