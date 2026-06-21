"""Tests for data sync, readiness badges, and the catalog browser."""

from datetime import timedelta
from unittest import mock

from django.contrib.gis.geos import Polygon
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from datasets.models import DataSource
from datasets.readiness import (
    layer_provenance_map,
    source_provenance,
    source_readiness,
    workspace_data_basis,
)
from datasets.views import _run_sync
from workspaces.models import ConnectorAuditLog, Workspace


class SyncAuditLoggingTests(TestCase):
    """Test that connector syncs are logged to the audit log."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="test-city",
            name="Test City",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )

    def test_sync_success_creates_audit_log_entry(self):
        """Successful sync creates log entry with status=success."""
        source = DataSource.objects.create(
            workspace=self.workspace,
            name="Test GeoJSON",
            source_type=DataSource.SourceType.GEOJSON_URL,
            layer_kind=DataSource.LayerKind.STREETS,
            config={"url": "https://example.com/test.geojson"},
        )

        mock_features = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                    "properties": {"name": "test"},
                }
            ],
        }
        mock_result = mock.Mock(feature_collection=mock_features, record_count=1)

        with mock.patch(
            "datasets.views.get_connector"
        ) as mock_get_connector, mock.patch(
            "datasets.views.NormalizedFeatureSet.objects.update_or_create"
        ):
            mock_connector = mock.Mock()
            mock_connector.validate_config.return_value = []
            mock_connector.fetch.return_value = mock_result
            mock_get_connector.return_value = mock_connector

            success, message = _run_sync(source)

        self.assertTrue(success)
        self.assertEqual(source.status, DataSource.Status.ACTIVE)

        log_entry = ConnectorAuditLog.objects.get(datasource=source)
        self.assertEqual(log_entry.status, ConnectorAuditLog.Status.SUCCESS)
        self.assertEqual(log_entry.feature_count, 1)
        self.assertIsNone(log_entry.error_message)
        self.assertIsNotNone(log_entry.duration_ms)
        self.assertGreater(log_entry.duration_ms, 0)

    def test_sync_error_creates_audit_log_entry(self):
        """Failed sync creates log entry with status=error."""
        source = DataSource.objects.create(
            workspace=self.workspace,
            name="Test GeoJSON",
            source_type=DataSource.SourceType.GEOJSON_URL,
            layer_kind=DataSource.LayerKind.STREETS,
            config={"url": "https://example.com/test.geojson"},
        )

        with mock.patch("datasets.views.get_connector") as mock_get_connector:
            mock_connector = mock.Mock()
            mock_connector.validate_config.return_value = []
            mock_connector.fetch.side_effect = Exception("Network error")
            mock_get_connector.return_value = mock_connector

            success, message = _run_sync(source)

        self.assertFalse(success)
        self.assertEqual(source.status, DataSource.Status.ERROR)

        log_entry = ConnectorAuditLog.objects.get(datasource=source)
        self.assertEqual(log_entry.status, ConnectorAuditLog.Status.ERROR)
        self.assertIn("Network error", log_entry.error_message)
        self.assertIsNone(log_entry.feature_count)
        self.assertIsNotNone(log_entry.duration_ms)

    def test_config_validation_error_creates_audit_log(self):
        """Config validation failure logs error."""
        source = DataSource.objects.create(
            workspace=self.workspace,
            name="Test GeoJSON",
            source_type=DataSource.SourceType.GEOJSON_URL,
            layer_kind=DataSource.LayerKind.STREETS,
            config={},  # Missing required url
        )

        with mock.patch("datasets.views.get_connector") as mock_get_connector:
            mock_connector = mock.Mock()
            mock_connector.validate_config.return_value = ["URL is required"]
            mock_get_connector.return_value = mock_connector

            success, message = _run_sync(source)

        self.assertFalse(success)
        self.assertEqual(source.status, DataSource.Status.ERROR)

        log_entry = ConnectorAuditLog.objects.get(datasource=source)
        self.assertEqual(log_entry.status, ConnectorAuditLog.Status.ERROR)
        self.assertIn("Configuration incomplete", log_entry.error_message)


class SourceReadinessTests(TestCase):
    """`source_readiness` collapses status + record_count + last_synced_at into
    a single badge level."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="readiness-test",
            name="Readiness Test",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )

    def _make(self, **overrides):
        defaults = {
            "workspace": self.workspace,
            "name": "S",
            "source_type": DataSource.SourceType.GEOJSON_URL,
            "layer_kind": DataSource.LayerKind.STREETS,
            "config": {"url": "https://example.com/x.geojson"},
        }
        defaults.update(overrides)
        return DataSource.objects.create(**defaults)

    def test_error_status_overrides_everything(self):
        src = self._make(
            status=DataSource.Status.ERROR,
            last_synced_at=timezone.now(),
            record_count=10_000,
        )
        self.assertEqual(source_readiness(src)["level"], "error")

    def test_never_synced_is_empty(self):
        src = self._make()
        self.assertEqual(source_readiness(src)["level"], "empty")

    def test_zero_records_is_empty(self):
        src = self._make(
            status=DataSource.Status.ACTIVE,
            last_synced_at=timezone.now(),
            record_count=0,
        )
        self.assertEqual(source_readiness(src)["level"], "empty")

    def test_old_sync_is_stale(self):
        src = self._make(
            status=DataSource.Status.ACTIVE,
            last_synced_at=timezone.now() - timedelta(days=45),
            record_count=500,
        )
        self.assertEqual(source_readiness(src)["level"], "stale")

    def test_low_record_count_is_thin(self):
        src = self._make(
            status=DataSource.Status.ACTIVE,
            last_synced_at=timezone.now(),
            record_count=10,
        )
        self.assertEqual(source_readiness(src)["level"], "thin")

    def test_recent_and_full_is_good(self):
        src = self._make(
            status=DataSource.Status.ACTIVE,
            last_synced_at=timezone.now(),
            record_count=500,
        )
        self.assertEqual(source_readiness(src)["level"], "good")


class SourceProvenanceTests(TestCase):
    """`source_provenance`, `layer_provenance_map`, and `workspace_data_basis`
    expose how real each source is — the public-facing trust signal."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="provenance-test",
            name="Provenance Test",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )

    def _make(self, **overrides):
        defaults = {
            "workspace": self.workspace,
            "name": "S",
            "source_type": DataSource.SourceType.GEOJSON_URL,
            "layer_kind": DataSource.LayerKind.STREETS,
            "config": {"url": "https://example.com/x.geojson"},
        }
        defaults.update(overrides)
        return DataSource.objects.create(**defaults)

    def test_default_provenance_is_live(self):
        src = self._make()
        self.assertEqual(src.provenance, DataSource.Provenance.LIVE)
        self.assertEqual(source_provenance(src)["level"], "live")

    def test_snapshot_and_demo_levels(self):
        snap = self._make(name="Snap", provenance=DataSource.Provenance.OFFICIAL_SNAPSHOT)
        demo = self._make(name="Demo", provenance=DataSource.Provenance.ILLUSTRATIVE_DEMO)
        self.assertEqual(source_provenance(snap)["level"], "snapshot")
        self.assertEqual(source_provenance(demo)["level"], "demo")

    def test_layer_provenance_reports_weakest_source(self):
        # A live and a demo source on the same layer → the layer reads as demo.
        self._make(name="Live streets", provenance=DataSource.Provenance.LIVE)
        self._make(name="Demo streets", provenance=DataSource.Provenance.ILLUSTRATIVE_DEMO)
        result = layer_provenance_map(self.workspace)
        self.assertEqual(result[DataSource.LayerKind.STREETS]["level"], "demo")

    def test_layer_provenance_skips_disabled_sources(self):
        self._make(name="Live streets", provenance=DataSource.Provenance.LIVE)
        self._make(
            name="Demo streets",
            provenance=DataSource.Provenance.ILLUSTRATIVE_DEMO,
            is_enabled=False,
        )
        result = layer_provenance_map(self.workspace)
        self.assertEqual(result[DataSource.LayerKind.STREETS]["level"], "live")

    def test_data_basis_counts_and_flags_demo(self):
        self._make(name="A", provenance=DataSource.Provenance.LIVE)
        self._make(name="B", provenance=DataSource.Provenance.OFFICIAL_SNAPSHOT)
        self._make(name="C", provenance=DataSource.Provenance.ILLUSTRATIVE_DEMO)
        basis = workspace_data_basis(self.workspace)
        self.assertEqual(basis["total"], 3)
        self.assertEqual(basis["live"], 1)
        self.assertEqual(basis["snapshot"], 1)
        self.assertEqual(basis["demo"], 1)
        self.assertTrue(basis["has_demo"])
        # worst badge across the mix is the demo tier
        self.assertEqual(basis["worst"]["level"], "demo")

    def test_methodology_page_warns_about_demo_data(self):
        self._make(
            name="Beispiel — Unfälle",
            layer_kind=DataSource.LayerKind.ACCIDENTS,
            provenance=DataSource.Provenance.ILLUSTRATIVE_DEMO,
        )
        response = Client().get(
            reverse("workspace_methodology", kwargs={"workspace_slug": self.workspace.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Illustrative demo")
        self.assertContains(response, "not real measurements")


@override_settings(ADMIN_TOKEN="test-token")
class CatalogViewsTests(TestCase):
    """End-to-end coverage for the new catalog-browser URLs."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="catalog-views",
            name="Catalog Views",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )
        self.client = Client()
        # Mark the session as admin by sending the bearer token on every
        # request — matches the production middleware contract.
        self.admin_headers = {"HTTP_AUTHORIZATION": "Bearer test-token"}

    def test_catalog_index_lists_only_searchable_connectors(self):
        response = self.client.get(
            reverse("catalog_index", kwargs={"workspace_slug": self.workspace.slug}),
            **self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        # Mobilithek is a real searchable catalogue and stays.
        self.assertContains(response, "Mobilithek")
        # Unfallatlas was removed from the catalog (single nationwide source —
        # added via the standard "Add data source" form instead).
        self.assertNotContains(response, "Unfallat")

    def test_catalog_browse_unknown_connector_redirects(self):
        response = self.client.get(
            reverse(
                "catalog_browse",
                kwargs={"workspace_slug": self.workspace.slug, "connector_id": "csv"},
            ),
            **self.admin_headers,
        )
        # CSV connector does not support discovery → redirect back to hub.
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.workspace.slug, response["Location"])

    def test_catalog_browse_unfallat_no_longer_discoverable(self):
        response = self.client.get(
            reverse(
                "catalog_browse",
                kwargs={"workspace_slug": self.workspace.slug, "connector_id": "unfallat"},
            ),
            **self.admin_headers,
        )
        # Removed from the catalog → redirect back to the data hub.
        self.assertEqual(response.status_code, 302)

    def test_catalog_add_creates_data_source_and_runs_sync(self):
        from connectors.base import CatalogEntry, CatalogPage

        fake_page = CatalogPage(
            entries=[
                CatalogEntry(
                    entry_id="mobilithek:gtfs-1",
                    title="GTFS Sachsen",
                    suggested_name="GTFS Sachsen",
                    suggested_layer_kind="transit_stops",
                    suggested_config={
                        "distribution_url": "https://example.org/feed.zip",
                        "format_hint": "gtfs",
                        "mode": "open",
                    },
                    license="dl-de/by-2-0",
                    attribution="DB",
                )
            ],
            total=1,
        )
        with mock.patch(
            "connectors.mobilithek_connector.MobilithekConnector.discover",
            return_value=fake_page,
        ), mock.patch("datasets.views._run_sync", return_value=(True, "Synced 5 records.")):
            response = self.client.post(
                reverse(
                    "catalog_add",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "mobilithek",
                    },
                ),
                {"entry_id": "mobilithek:gtfs-1"},
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        src = DataSource.objects.get(workspace=self.workspace, name="GTFS Sachsen")
        self.assertEqual(src.source_type, "mobilithek")
        self.assertEqual(src.config["distribution_url"], "https://example.org/feed.zip")
        self.assertEqual(src.license, "dl-de/by-2-0")

    def test_catalog_add_idempotent(self):
        from connectors.base import CatalogEntry, CatalogPage

        fake_page = CatalogPage(
            entries=[
                CatalogEntry(
                    entry_id="mobilithek:gtfs-1",
                    title="GTFS Sachsen",
                    suggested_name="GTFS Sachsen",
                    suggested_layer_kind="transit_stops",
                    suggested_config={"distribution_url": "https://example.org/feed.zip"},
                )
            ],
            total=1,
        )
        with mock.patch(
            "connectors.mobilithek_connector.MobilithekConnector.discover",
            return_value=fake_page,
        ), mock.patch("datasets.views._run_sync", return_value=(True, "ok")):
            for _ in range(2):
                self.client.post(
                    reverse(
                        "catalog_add",
                        kwargs={
                            "workspace_slug": self.workspace.slug,
                            "connector_id": "mobilithek",
                        },
                    ),
                    {"entry_id": "mobilithek:gtfs-1"},
                    **self.admin_headers,
                )
        self.assertEqual(
            DataSource.objects.filter(
                workspace=self.workspace, name="GTFS Sachsen"
            ).count(),
            1,
        )

    def test_catalog_add_rejects_unknown_entry(self):
        from connectors.base import CatalogPage

        with mock.patch(
            "connectors.mobilithek_connector.MobilithekConnector.discover",
            return_value=CatalogPage(),
        ):
            response = self.client.post(
                reverse(
                    "catalog_add",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "mobilithek",
                    },
                ),
                {"entry_id": "nope"},
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataSource.objects.filter(workspace=self.workspace).exists())

    def test_catalog_quickadd_creates_source_from_distribution_url(self):
        with mock.patch(
            "datasets.views._run_sync", return_value=(True, "Synced 5.")
        ):
            response = self.client.post(
                reverse(
                    "catalog_quickadd",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "mobilithek",
                    },
                ),
                {
                    "name": "GTFS Sachsen",
                    "distribution_url": "https://example.org/feed.zip",
                    "format_hint": "gtfs",
                },
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        src = DataSource.objects.get(workspace=self.workspace, name="GTFS Sachsen")
        self.assertEqual(src.config["distribution_url"], "https://example.org/feed.zip")

    def test_catalog_quickadd_validation_error_redirects_with_message(self):
        response = self.client.post(
            reverse(
                "catalog_quickadd",
                kwargs={
                    "workspace_slug": self.workspace.slug,
                    "connector_id": "mobilithek",
                },
            ),
            # Unsupported format → quick_add raises ValueError.
            {"name": "x", "distribution_url": "https://example/x", "format_hint": "pdf"},
            **self.admin_headers,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataSource.objects.filter(workspace=self.workspace).exists())

    def test_catalog_quickadd_requires_admin(self):
        response = self.client.post(
            reverse(
                "catalog_quickadd",
                kwargs={
                    "workspace_slug": self.workspace.slug,
                    "connector_id": "mobilithek",
                },
            ),
            {
                "name": "GTFS Sachsen",
                "distribution_url": "https://example.org/feed.zip",
                "format_hint": "gtfs",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_catalog_browse_persists_mobilithek_url_override(self):
        with mock.patch(
            "connectors.mobilithek_catalog.browse_catalog", return_value=[]
        ):
            self.client.get(
                reverse(
                    "catalog_browse",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "mobilithek",
                    },
                ),
                {"catalog_url": "https://override.example/feed.rdf"},
                **self.admin_headers,
            )
        self.workspace.refresh_from_db()
        self.assertEqual(
            self.workspace.settings.get("mobilithek_catalog_url"),
            "https://override.example/feed.rdf",
        )

    def test_catalog_browse_does_not_persist_url_for_non_admin(self):
        with mock.patch(
            "connectors.mobilithek_catalog.browse_catalog", return_value=[]
        ):
            self.client.get(
                reverse(
                    "catalog_browse",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "mobilithek",
                    },
                ),
                {"catalog_url": "https://override.example/feed.rdf"},
            )
        self.workspace.refresh_from_db()
        self.assertNotIn("mobilithek_catalog_url", self.workspace.settings or {})

    def test_catalog_add_requires_admin(self):
        response = self.client.post(
            reverse(
                "catalog_add",
                kwargs={
                    "workspace_slug": self.workspace.slug,
                    "connector_id": "unfallat",
                },
            ),
            {"entry_id": "unfallatlas-2024"},
        )
        self.assertEqual(response.status_code, 403)


class DataHubReadinessRenderingTests(TestCase):
    """The data hub view computes KPIs and passes per-source readiness to the
    template."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="hub-render",
            name="Hub Render",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )
        self.client = Client()

    def test_empty_source_shows_no_data_badge(self):
        DataSource.objects.create(
            workspace=self.workspace,
            name="Untouched source",
            source_type=DataSource.SourceType.GEOJSON_URL,
            layer_kind=DataSource.LayerKind.STREETS,
            config={"url": "https://example.com/x.geojson"},
        )
        response = self.client.get(
            reverse("data_hub", kwargs={"workspace_slug": self.workspace.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Untouched source")
        self.assertContains(response, "No data")


@override_settings(ADMIN_TOKEN="test-token")
class AddDataSourceFormTests(TestCase):
    """Ensure the Add-source form preserves operator input on validation
    errors and reports JSON parse failures with line/column info — the
    previous behaviour was to flash a generic error and redirect, losing
    everything the operator had pasted."""

    def setUp(self):
        self.workspace = Workspace.objects.create(
            slug="add-form",
            name="Add Form",
            country_code="DE",
            bounds=Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
        )
        self.client = Client()
        self.admin_headers = {"HTTP_AUTHORIZATION": "Bearer test-token"}

    def test_invalid_json_re_renders_with_input_preserved(self):
        response = self.client.post(
            reverse("data_source_add", kwargs={"workspace_slug": self.workspace.slug}),
            {
                "name": "My broken source",
                "source_type": "unfallat",
                "layer_kind": "accidents",
                "config": "{not valid json",
                "license": "dl-de/by-2-0",
            },
            **self.admin_headers,
        )
        # Re-renders the form (no redirect) and does NOT persist a row.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DataSource.objects.filter(workspace=self.workspace).exists())
        # The operator's input is in the rendered HTML (so they can fix it).
        self.assertContains(response, "My broken source")
        self.assertContains(response, "{not valid json")
        # The error message names the parser location.
        self.assertContains(response, "line ")

    def test_valid_json_creates_source(self):
        response = self.client.post(
            reverse("data_source_add", kwargs={"workspace_slug": self.workspace.slug}),
            {
                "name": "Unfallatlas 2024",
                "source_type": "unfallat",
                "layer_kind": "accidents",
                "config": '{"url": "https://example.org/u.zip"}',
            },
            **self.admin_headers,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            DataSource.objects.filter(
                workspace=self.workspace, name="Unfallatlas 2024"
            ).exists()
        )


class MobilitySnapshotCollectorTests(TestCase):
    """The collect_mobility_snapshots command stores grid snapshots."""

    def setUp(self):
        from django.contrib.gis.geos import Point

        self.ws = Workspace.objects.create(
            slug="snap-city",
            name="Snap City",
            country_code="DE",
            timezone="Europe/Berlin",
            center=Point(12.37, 51.34, srid=4326),
            bounds=Polygon(((12.2, 51.2), (12.6, 51.2), (12.6, 51.5), (12.2, 51.5), (12.2, 51.2))),
        )
        self.source = DataSource.objects.create(
            workspace=self.ws,
            name="GBFS bikes",
            source_type=DataSource.SourceType.GBFS,
            layer_kind=DataSource.LayerKind.SHARED_VEHICLES,
            config={"discovery_url": "https://x/gbfs.json", "layer": "shared_vehicles"},
        )

    def _fake_features(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [12.37, 51.34]},
                    "properties": {"form_factor": "bicycle"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [12.3702, 51.3402]},
                    "properties": {"form_factor": "bicycle"},
                },
            ],
        }

    def test_command_creates_snapshot(self):
        from django.core.management import call_command

        from datasets.models import MobilitySnapshot

        fake = mock.Mock(feature_collection=self._fake_features(), record_count=2)
        with mock.patch(
            "datasets.management.commands.collect_mobility_snapshots.get_connector"
        ) as get_conn:
            get_conn.return_value.fetch.return_value = fake
            call_command("collect_mobility_snapshots", "--workspace", "snap-city")

        snaps = MobilitySnapshot.objects.filter(source=self.source)
        self.assertEqual(snaps.count(), 1)
        snap = snaps.first()
        self.assertEqual(snap.vehicle_count, 2)
        # Both vehicles fall in the same ~400 m cell.
        self.assertEqual(len(snap.cell_counts), 1)


class SharedMobilityGapsViewTests(TestCase):
    """The public gap-analysis API aggregates snapshots into a cell grid."""

    def setUp(self):
        from django.contrib.gis.geos import Point

        from datasets.mobility_gaps import bin_features_to_grid, grid_steps
        from datasets.models import MobilitySnapshot

        self.ws = Workspace.objects.create(
            slug="gap-city",
            name="Gap City",
            country_code="DE",
            timezone="Europe/Berlin",
            center=Point(12.37, 51.34, srid=4326),
            is_active=True,
        )
        self.source = DataSource.objects.create(
            workspace=self.ws,
            name="GBFS bikes",
            source_type=DataSource.SourceType.GBFS,
            layer_kind=DataSource.LayerKind.SHARED_VEHICLES,
            config={},
        )
        self.lon_step, self.lat_step = grid_steps(51.34, 400)

        def grid_for(points):
            feats = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": list(p)},
                    "properties": {"form_factor": "bicycle"},
                }
                for p in points
            ]
            return bin_features_to_grid(feats, self.lon_step, self.lat_step)

        now = timezone.now()
        # Two snapshots: a busy spot present both times, a fringe spot once.
        for offset, points in enumerate(
            [[(12.37, 51.34), (12.45, 51.40)], [(12.37, 51.34)]]
        ):
            MobilitySnapshot.objects.create(
                source=self.source,
                workspace=self.ws,
                captured_at=now - timedelta(hours=offset),
                vehicle_count=len(points),
                cell_counts=grid_for(points),
                cell_size_m=400,
                lon_step=self.lon_step,
                lat_step=self.lat_step,
            )

    def test_gap_view_returns_cells_with_gap_rate(self):
        client = Client()
        url = reverse("api_shared_mobility_gaps", args=["gap-city"])
        resp = client.get(url, {"days": "7"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["samples"], 2)
        self.assertEqual(data["type"], "FeatureCollection")
        gap_rates = sorted(f["properties"]["gap_rate"] for f in data["features"])
        # One cell always present (gap 0.0), one present half the time (0.5).
        self.assertIn(0.0, gap_rates)
        self.assertIn(0.5, gap_rates)

    def test_gap_view_without_snapshots_is_empty(self):
        client = Client()
        Workspace.objects.create(
            slug="bare-city", name="Bare", country_code="DE", is_active=True
        )
        url = reverse("api_shared_mobility_gaps", args=["bare-city"])
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["samples"], 0)
