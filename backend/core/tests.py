"""Unit tests for the platform context processor.

Pure, DB-free tests per the CLAUDE.md testing rule — they only assert that the
processor surfaces the configured settings to templates.
"""

from django.test import RequestFactory, TestCase, override_settings

from core.context_processors import platform_context


class PlatformContextTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def test_exposes_all_basemap_tile_settings(self):
        ctx = platform_context(self.request)
        for key in (
            "map_tile_url",
            "map_tile_attribution",
            "map_tile_url_dark",
            "map_tile_attribution_dark",
            "map_tile_url_satellite",
            "map_tile_attribution_satellite",
        ):
            self.assertIn(key, ctx)

    @override_settings(
        MAP_TILE_URL_SATELLITE="https://example.test/{z}/{y}/{x}",
        MAP_TILE_ATTRIBUTION_SATELLITE="© Example Imagery",
    )
    def test_satellite_settings_are_passed_through(self):
        ctx = platform_context(self.request)
        self.assertEqual(ctx["map_tile_url_satellite"], "https://example.test/{z}/{y}/{x}")
        self.assertEqual(ctx["map_tile_attribution_satellite"], "© Example Imagery")

    @override_settings(MAP_TILE_URL_SATELLITE="")
    def test_satellite_can_be_disabled(self):
        # An empty satellite URL is the signal the map uses to hide the option.
        self.assertEqual(platform_context(self.request)["map_tile_url_satellite"], "")
