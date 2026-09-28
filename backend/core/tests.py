"""Unit tests for the platform context processor.

Pure, DB-free tests per the CLAUDE.md testing rule — they only assert that the
processor surfaces the configured settings to templates.
"""

from django.test import RequestFactory, TestCase, override_settings

from core.context_processors import LEGACY_KEYLESS_DARK_TILE_URL, platform_context


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

    @override_settings(MAP_TILE_URL_DARK="https://tiles.example.test/dark/{z}/{x}/{y}.png")
    def test_dark_tile_url_is_passed_through(self):
        self.assertEqual(
            platform_context(self.request)["map_tile_url_dark"],
            "https://tiles.example.test/dark/{z}/{x}/{y}.png",
        )

    @override_settings(MAP_TILE_URL_DARK="")
    def test_empty_dark_tile_url_stays_empty(self):
        # Empty tells the map to darken the light tiles itself.
        self.assertEqual(platform_context(self.request)["map_tile_url_dark"], "")

    @override_settings(MAP_TILE_URL_DARK=LEGACY_KEYLESS_DARK_TILE_URL)
    def test_legacy_keyless_dark_url_falls_back_to_derived_dark(self):
        # The old default now serves "API key required" tiles; installs whose
        # .env still carries it must get a working dark map after upgrading.
        self.assertEqual(platform_context(self.request)["map_tile_url_dark"], "")

    @override_settings(MAP_TILE_URL_DARK=LEGACY_KEYLESS_DARK_TILE_URL + "?key=abc")
    def test_keyed_dark_url_is_kept(self):
        self.assertEqual(
            platform_context(self.request)["map_tile_url_dark"],
            LEGACY_KEYLESS_DARK_TILE_URL + "?key=abc",
        )
