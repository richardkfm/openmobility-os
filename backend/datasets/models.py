"""Data sources and normalized feature sets.

Every dataset in OpenMobility OS is a GeoJSON `FeatureCollection` produced by
a connector. Core code never touches raw vendor-specific formats — connectors
are responsible for normalization.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class DataSource(models.Model):
    """A configured data source for a workspace."""

    class SourceType(models.TextChoices):
        CSV = "csv", _("CSV (upload or URL)")
        GEOJSON_URL = "geojson_url", _("GeoJSON URL")
        OSM_OVERPASS = "osm_overpass", _("OpenStreetMap (Overpass API)")
        MANUAL = "manual", _("Manual KPI entry")
        GTFS = "gtfs", _("GTFS static (transit schedule)")
        CKAN = "ckan", _("CKAN open-data portal (planned)")
        WFS = "wfs", _("WFS geo-service (planned)")
        REST = "rest", _("Generic REST JSON (planned)")

    class LayerKind(models.TextChoices):
        STREETS = "streets", _("Streets")
        STREETS_WITH_SPEED = "streets_with_speed", _("Streets with speed limits")
        BIKE_NETWORK = "bike_network", _("Bike network")
        TRANSIT_STOPS = "transit_stops", _("Transit stops")
        TRANSIT_ROUTES = "transit_routes", _("Transit routes")
        TRANSIT_COVERAGE = "transit_coverage", _("Transit coverage (buffer)")
        ACCIDENTS = "accidents", _("Accidents")
        PARKING = "parking", _("Parking")
        DISTRICTS = "districts", _("Districts / neighborhoods")
        SCHOOLS = "schools", _("Schools")
        AIR_QUALITY = "air_quality", _("Air quality stations")
        LAND_USE = "land_use", _("Land use")
        TREES = "trees", _("Tree cadastre")
        GREEN_AREAS = "green_areas", _("Green areas / parks")
        SEALED_SURFACES = "sealed_surfaces", _("Sealed surfaces")
        HEAT_CORRIDORS = "heat_corridors", _("Heat / fresh-air corridors")
        WATER_BODIES = "water_bodies", _("Water bodies / retention areas")
        CUSTOM = "custom", _("Custom / other")

    class Status(models.TextChoices):
        UNSYNCED = "unsynced", _("Never synced")
        PENDING = "pending", _("Sync pending")
        ACTIVE = "active", _("Active")
        ERROR = "error", _("Error")

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="data_sources"
    )
    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    layer_kind = models.CharField(
        max_length=30, choices=LayerKind.choices, default=LayerKind.CUSTOM
    )
    config = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNSYNCED)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    record_count = models.PositiveIntegerField(null=True, blank=True)

    license = models.CharField(max_length=200, blank=True)
    attribution = models.CharField(max_length=500, blank=True)
    source_url = models.URLField(blank=True)

    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workspace", "name"]

    def __str__(self):
        return f"{self.workspace.slug}/{self.name}"


class NormalizedFeatureSet(models.Model):
    """Latest normalized GeoJSON produced by a data source."""

    source = models.OneToOneField(
        DataSource, on_delete=models.CASCADE, related_name="normalized"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="normalized_feature_sets",
    )
    layer_kind = models.CharField(max_length=30)
    feature_collection = models.JSONField()
    record_count = models.PositiveIntegerField(default=0)
    schema_version = models.CharField(max_length=20, default="1.0")
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "layer_kind"])]

    def __str__(self):
        return f"{self.workspace.slug}/{self.layer_kind}"
