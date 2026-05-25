"""Tests for data sync and audit logging."""

from unittest import mock

from django.contrib.gis.geos import Polygon
from django.test import TestCase

from datasets.models import DataSource
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
