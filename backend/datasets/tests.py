"""Tests for data sync, readiness badges, and the catalog browser."""

from datetime import timedelta
from unittest import mock

from django.contrib.gis.geos import Polygon
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from datasets.models import DataSource
from datasets.readiness import source_readiness
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

    def test_catalog_index_lists_discoverable_connectors(self):
        response = self.client.get(
            reverse("catalog_index", kwargs={"workspace_slug": self.workspace.slug}),
            **self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        # Both Mobilithek and Unfallatlas implement supports_discovery=True.
        self.assertContains(response, "Mobilithek")
        self.assertContains(response, "Unfallat")

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

    def test_catalog_add_creates_data_source_and_runs_sync(self):
        from connectors.base import CatalogEntry, CatalogPage

        fake_page = CatalogPage(
            entries=[
                CatalogEntry(
                    entry_id="unfallatlas-2024",
                    title="Unfallatlas 2024",
                    suggested_name="Unfallatlas 2024",
                    suggested_layer_kind="accidents",
                    suggested_config={
                        "url": "https://example.org/u-2024.csv",
                        "encoding": "utf-8",
                        "clip_to_workspace": True,
                    },
                    license="dl-de/by-2-0",
                    attribution="© Destatis",
                )
            ],
            total=1,
        )
        with mock.patch(
            "connectors.unfallat_connector.UnfallatlasConnector.discover",
            return_value=fake_page,
        ), mock.patch("datasets.views._run_sync", return_value=(True, "Synced 5 records.")):
            response = self.client.post(
                reverse(
                    "catalog_add",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "unfallat",
                    },
                ),
                {"entry_id": "unfallatlas-2024"},
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        src = DataSource.objects.get(workspace=self.workspace, name="Unfallatlas 2024")
        self.assertEqual(src.source_type, "unfallat")
        self.assertEqual(src.layer_kind, DataSource.LayerKind.ACCIDENTS)
        self.assertEqual(src.config["url"], "https://example.org/u-2024.csv")
        self.assertEqual(src.license, "dl-de/by-2-0")

    def test_catalog_add_idempotent(self):
        from connectors.base import CatalogEntry, CatalogPage

        fake_page = CatalogPage(
            entries=[
                CatalogEntry(
                    entry_id="unfallatlas-2024",
                    title="Unfallatlas 2024",
                    suggested_name="Unfallatlas 2024",
                    suggested_layer_kind="accidents",
                    suggested_config={"url": "https://example.org/u-2024.csv"},
                )
            ],
            total=1,
        )
        with mock.patch(
            "connectors.unfallat_connector.UnfallatlasConnector.discover",
            return_value=fake_page,
        ), mock.patch("datasets.views._run_sync", return_value=(True, "ok")):
            for _ in range(2):
                self.client.post(
                    reverse(
                        "catalog_add",
                        kwargs={
                            "workspace_slug": self.workspace.slug,
                            "connector_id": "unfallat",
                        },
                    ),
                    {"entry_id": "unfallatlas-2024"},
                    **self.admin_headers,
                )
        self.assertEqual(
            DataSource.objects.filter(
                workspace=self.workspace, name="Unfallatlas 2024"
            ).count(),
            1,
        )

    def test_catalog_add_rejects_unknown_entry(self):
        from connectors.base import CatalogPage

        with mock.patch(
            "connectors.unfallat_connector.UnfallatlasConnector.discover",
            return_value=CatalogPage(),
        ):
            response = self.client.post(
                reverse(
                    "catalog_add",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "unfallat",
                    },
                ),
                {"entry_id": "nope"},
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataSource.objects.filter(workspace=self.workspace).exists())

    def test_catalog_quickadd_creates_source_for_custom_year(self):
        with mock.patch(
            "datasets.views._run_sync", return_value=(True, "Synced 5.")
        ):
            response = self.client.post(
                reverse(
                    "catalog_quickadd",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "unfallat",
                    },
                ),
                {
                    "year": "2024",
                    "url": "https://destatis.example/u-2024.csv",
                    "encoding": "utf-8",
                },
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        src = DataSource.objects.get(workspace=self.workspace, name="Unfallatlas 2024")
        self.assertEqual(src.config["url"], "https://destatis.example/u-2024.csv")

    def test_catalog_quickadd_validation_error_redirects_with_message(self):
        response = self.client.post(
            reverse(
                "catalog_quickadd",
                kwargs={
                    "workspace_slug": self.workspace.slug,
                    "connector_id": "unfallat",
                },
            ),
            {"year": "abc", "url": "https://example/x.csv"},
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
                    "connector_id": "unfallat",
                },
            ),
            {"year": "2024", "url": "https://example/u.csv"},
        )
        self.assertEqual(response.status_code, 403)

    def test_catalog_quickadd_accepts_uploaded_file(self):
        """Uploading a CSV in the catalog quick-add must create the source,
        store the file, and point config['url'] at the saved path — the path
        that solves the 'Destatis gives no direct URL' problem."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_bytes = (
            b"OBJECTID,UJAHR,UMONAT,USTUNDE,UWOCHENTAG,UKATEGORIE,UART,UTYP1,"
            b"ULICHTVERH,IstRad,IstPKW,IstFuss,IstKrad,IstGkfz,IstSonstig,"
            b"STRZUSTAND,LON,LAT\n"
            b"1,2024,5,14,3,2,5,1,0,1,1,0,0,0,0,0,12.3731,51.3397\n"
        )
        upload = SimpleUploadedFile(
            "unfaelle_2024.csv", csv_bytes, content_type="text/csv"
        )
        with mock.patch(
            "datasets.views._run_sync", return_value=(True, "Synced 1.")
        ):
            response = self.client.post(
                reverse(
                    "catalog_quickadd",
                    kwargs={
                        "workspace_slug": self.workspace.slug,
                        "connector_id": "unfallat",
                    },
                ),
                {"year": "2024", "source_file": upload},
                **self.admin_headers,
            )
        self.assertEqual(response.status_code, 302)
        src = DataSource.objects.get(workspace=self.workspace, name="Unfallatlas 2024")
        self.assertTrue(src.source_file)
        # config url points at the stored file (absolute path), not a remote URL.
        self.assertEqual(src.config["url"], src.source_file.path)
        self.assertTrue(src.config["url"].endswith(".csv"))

    def test_catalog_quickadd_rejects_no_url_no_file(self):
        response = self.client.post(
            reverse(
                "catalog_quickadd",
                kwargs={
                    "workspace_slug": self.workspace.slug,
                    "connector_id": "unfallat",
                },
            ),
            {"year": "2024"},
            **self.admin_headers,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataSource.objects.filter(workspace=self.workspace).exists())

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
