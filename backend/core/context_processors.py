"""Template context processor exposing platform-level state."""

from django.conf import settings

# The dark basemap default up to 0.55.1, which .env.example also shipped, so
# many installs still set it. CARTO now answers keyless requests with "API key
# required" tiles, so this exact URL is treated as unset and those installs get
# the keyless dark rendering of MAP_TILE_URL. A keyed URL is used as configured.
LEGACY_KEYLESS_DARK_TILE_URL = "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"


def _dark_tile_url():
    url = settings.MAP_TILE_URL_DARK.strip()
    return "" if url == LEGACY_KEYLESS_DARK_TILE_URL else url


def platform_context(request):
    return {
        "platform_version": settings.PLATFORM_VERSION,
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "default_workspace_slug": settings.DEFAULT_WORKSPACE_SLUG,
        "map_tile_url": settings.MAP_TILE_URL,
        "map_tile_attribution": settings.MAP_TILE_ATTRIBUTION,
        # Empty means "no dedicated dark tileset": the map darkens the light
        # tiles itself and credits them with map_tile_attribution.
        "map_tile_url_dark": _dark_tile_url(),
        "map_tile_attribution_dark": settings.MAP_TILE_ATTRIBUTION_DARK,
        "map_tile_url_satellite": settings.MAP_TILE_URL_SATELLITE,
        "map_tile_attribution_satellite": settings.MAP_TILE_ATTRIBUTION_SATELLITE,
        "project_repo_url": settings.PROJECT_REPO_URL,
        "project_release_url": settings.PROJECT_RELEASE_URL,
        "is_admin": getattr(request, "is_admin", False),
    }
