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

    @override_settings(MAP_TILE_URL_DARK=LEGACY_KEYLESS_DARK_TILE_URL)
    def test_legacy_keyless_dark_url_is_dropped(self):
        # The old default now serves "API key required" tiles; installs whose
        # .env still carries it must get a working dark map after upgrading.
        self.assertEqual(platform_context(self.request)["map_tile_url_dark"], "")

    @override_settings(MAP_TILE_URL_DARK=LEGACY_KEYLESS_DARK_TILE_URL + "?key=abc")
    def test_keyed_dark_url_is_kept(self):
        self.assertEqual(
            platform_context(self.request)["map_tile_url_dark"],
            LEGACY_KEYLESS_DARK_TILE_URL + "?key=abc",
        )


@override_settings(
    MAP_LIGHT_STYLE="raster",
    MAP_VECTOR_STYLE_URL_LIGHT="https://styles.example.test/light",
    MAP_DARK_STYLE="",
    MAP_VECTOR_STYLE_URL_DARK="https://styles.example.test/dark",
    MAP_TILE_URL_DARK="",
)
class BasemapStyleTests(TestCase):
    """MAP_LIGHT_STYLE / MAP_DARK_STYLE resolve to a style the map can draw."""

    def setUp(self):
        self.request = RequestFactory().get("/")

    def style(self, key):
        return platform_context(self.request)[key]

    def test_light_defaults_to_raster(self):
        self.assertEqual(self.style("map_light_style"), "raster")

    @override_settings(MAP_LIGHT_STYLE="vector")
    def test_light_vector(self):
        self.assertEqual(self.style("map_light_style"), "vector")
        self.assertEqual(self.style("map_vector_style_url_light"), "https://styles.example.test/light")

    @override_settings(MAP_LIGHT_STYLE="vector", MAP_VECTOR_STYLE_URL_LIGHT="")
    def test_light_vector_without_url_falls_back_to_raster(self):
        self.assertEqual(self.style("map_light_style"), "raster")

    def test_dark_defaults_to_vector(self):
        self.assertEqual(self.style("map_dark_style"), "vector")

    @override_settings(MAP_TILE_URL_DARK="https://tiles.example.test/dark/{z}/{x}/{y}.png")
    def test_unset_dark_style_keeps_a_configured_dark_tileset(self):
        self.assertEqual(self.style("map_dark_style"), "raster")

    @override_settings(MAP_TILE_URL_DARK=LEGACY_KEYLESS_DARK_TILE_URL)
    def test_legacy_dark_url_moves_to_vector(self):
        self.assertEqual(self.style("map_dark_style"), "vector")

    @override_settings(MAP_DARK_STYLE="Filter")
    def test_dark_filter_is_case_insensitive(self):
        self.assertEqual(self.style("map_dark_style"), "filter")

    @override_settings(
        MAP_DARK_STYLE="vector",
        MAP_TILE_URL_DARK="https://tiles.example.test/dark/{z}/{x}/{y}.png",
    )
    def test_explicit_dark_style_wins_over_a_dark_tileset(self):
        self.assertEqual(self.style("map_dark_style"), "vector")

    @override_settings(MAP_DARK_STYLE="vector", MAP_VECTOR_STYLE_URL_DARK="")
    def test_dark_vector_without_url_falls_back_to_filter(self):
        self.assertEqual(self.style("map_dark_style"), "filter")

    @override_settings(MAP_DARK_STYLE="raster")
    def test_dark_raster_without_tiles_falls_back_to_filter(self):
        self.assertEqual(self.style("map_dark_style"), "filter")

    @override_settings(MAP_DARK_STYLE="vectr")
    def test_unknown_dark_style_is_treated_as_unset(self):
        self.assertEqual(self.style("map_dark_style"), "vector")
