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
        GBFS = "gbfs", _("GBFS shared mobility (bikes/scooters/cars)")
        CKAN = "ckan", _("CKAN open-data portal")
        WFS = "wfs", _("WFS geo-service")
        REST = "rest", _("Generic REST JSON")
        MOBILITHEK = "mobilithek", _("Mobilithek (German NAP)")
        BNETZA_CHARGING = "bnetza_charging", _("BNetzA EV charging register")
        UBA_AIR = "uba_air", _("UBA air quality stations")
        DWD_CLIMATE = "dwd_climate", _("DWD climate stations")
        BAST_COUNTS = "bast_counts", _("BASt traffic count stations")
        ZENSUS_GRID = "zensus_grid", _("Zensus 2022 population grid")

    class LayerKind(models.TextChoices):
        STREETS = "streets", _("Streets")
        STREETS_WITH_SPEED = "streets_with_speed", _("Streets with speed limits")
        BIKE_NETWORK = "bike_network", _("Bike network")
        DEDICATED_BIKE_NETWORK = "dedicated_bike_network", _(
            "Dedicated bike lanes / paths"
        )
        TRANSIT_STOPS = "transit_stops", _("Transit stops")
        TRANSIT_ROUTES = "transit_routes", _("Transit routes")
        TRANSIT_COVERAGE = "transit_coverage", _("Transit coverage (buffer)")
        SHARED_VEHICLES = "shared_vehicles", _(
            "Shared mobility — available vehicles"
        )
        SHARED_STATIONS = "shared_stations", _("Shared mobility — stations")
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
        FLOOD_RISK = "flood_risk", _("Flood hazard zones")
        DROUGHT_RISK = "drought_risk", _("Drought / heat-stress areas")
        EV_CHARGING = "ev_charging", _("EV charging stations")
        TRAFFIC_COUNTS = "traffic_counts", _("Traffic counts")
        CYCLING_COUNTS = "cycling_counts", _("Cycling counts")
        NOISE = "noise", _("Noise contours")
        PUBLIC_BUILDINGS = "public_buildings", _("Public buildings / amenities")
        POPULATION_GRID = "population_grid", _("Population density grid")
        DEMOGRAPHICS = "demographics", _("Demographic indicators")
        CUSTOM = "custom", _("Custom / other")

    class Status(models.TextChoices):
        UNSYNCED = "unsynced", _("Never synced")
        PENDING = "pending", _("Sync pending")
        ACTIVE = "active", _("Active")
        ERROR = "error", _("Error")

    class Provenance(models.TextChoices):
        # A connector that pulls from a live, authoritative feed.
        LIVE = "live", _("Live source")
        # A stored copy of official data, vendored so the demo works offline;
        # may lag behind the live source it was generated from.
        OFFICIAL_SNAPSHOT = "official_snapshot", _("Official snapshot")
        # Hand-authored placeholder data that is not a real measurement.
        ILLUSTRATIVE_DEMO = "illustrative_demo", _("Illustrative demo")

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

    # Honest "is this real?" signal, surfaced to the public so visitors can
    # calibrate trust. Defaults to LIVE; demo configs mark placeholder layers
    # as ILLUSTRATIVE_DEMO and vendored official copies as OFFICIAL_SNAPSHOT.
    provenance = models.CharField(
        max_length=20,
        choices=Provenance.choices,
        default=Provenance.LIVE,
        verbose_name=_("Data provenance"),
        help_text=_(
            "Whether this source is a live feed, a stored snapshot of official "
            "data, or illustrative demo data that is not a real measurement."
        ),
    )

    error_message = models.TextField(blank=True)

    # Non-fatal warnings from the most recent sync attempt (e.g. "workspace
    # bounds clipped every row — imported unclipped fallback"). Shown on the
    # data source detail page until the next sync. Plain list of strings.
    last_sync_warnings = models.JSONField(default=list, blank=True)

    # Admin-controlled on/off switch — disabled sources are hidden from the map
    # and excluded from layer queries without being deleted.
    is_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Enabled"),
        help_text=_("Disabled sources are not shown on the map."),
    )

    # Optional uploaded source file (CSV, GeoJSON). When set, the connector
    # reads from this file instead of fetching a remote URL.
    source_file = models.FileField(
        upload_to="datasource_files/%Y/%m/",
        blank=True,
        null=True,
        verbose_name=_("Source file"),
        help_text=_("Upload a CSV or GeoJSON file directly instead of providing a URL."),
    )

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


class MobilitySnapshot(models.Model):
    """One time-stamped observation of a shared-mobility source.

    GBFS feeds are real-time only, so to support temporal availability / gap
    analysis we sample a source on a schedule (see the
    ``collect_mobility_snapshots`` management command) and store each sample as
    a compact spatial-grid aggregation rather than raw points. Free-floating
    vehicle IDs rotate and have no fixed home, so a fixed grid is the stable
    unit of analysis for both free-floating and station feeds.

    ``cell_counts`` maps a grid-cell key (``"i:j"``) to a per-form-factor
    count of available vehicles, e.g. ``{"42:88": {"bicycle": 3, "car": 1}}``.
    ``lon_step`` / ``lat_step`` record the grid resolution used so the cells
    can be reconstructed as polygons later, even if the default cell size
    changes.
    """

    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="mobility_snapshots"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="mobility_snapshots",
    )
    captured_at = models.DateTimeField(db_index=True)
    vehicle_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Total available vehicles observed in this snapshot."),
    )
    cell_counts = models.JSONField(default=dict)
    cell_size_m = models.PositiveIntegerField(default=400)
    lon_step = models.FloatField()
    lat_step = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["source", "captured_at"])]
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.source}/{self.captured_at:%Y-%m-%d %H:%M}"

