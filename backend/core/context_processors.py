"""Template context processor exposing platform-level state."""

from django.conf import settings

# The dark basemap default up to 0.55.1, which .env.example also shipped, so
# many installs still set it. CARTO now answers keyless requests with "API key
# required" tiles, so this exact URL is treated as unset. A keyed URL is used
# as configured.
LEGACY_KEYLESS_DARK_TILE_URL = "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"

DARK_STYLES = ("vector", "filter", "raster")


def _dark_tile_url():
    url = settings.MAP_TILE_URL_DARK.strip()
    return "" if url == LEGACY_KEYLESS_DARK_TILE_URL else url


def _light_style():
    """Return "vector" when asked for and a style URL is set, else "raster"."""
    wanted = settings.MAP_LIGHT_STYLE.strip().lower()
    if wanted == "vector" and settings.MAP_VECTOR_STYLE_URL_LIGHT.strip():
        return "vector"
    return "raster"


def _dark_style(dark_tile_url):
    """Resolve MAP_DARK_STYLE to a style the map can draw with the URLs it has.

    Unset (or unrecognised) keeps a dedicated dark tileset where one is
    configured, so installs that point MAP_TILE_URL_DARK at their own tiles
    are not switched over. The filter needs nothing beyond MAP_TILE_URL, so it
    is the fallback for a style whose URL is missing.
    """
    wanted = settings.MAP_DARK_STYLE.strip().lower()
    if wanted not in DARK_STYLES:
        wanted = "raster" if dark_tile_url else "vector"
    if wanted == "vector" and not settings.MAP_VECTOR_STYLE_URL_DARK.strip():
        return "filter"
    if wanted == "raster" and not dark_tile_url:
        return "filter"
    return wanted


def platform_context(request):
    dark_tile_url = _dark_tile_url()
    return {
        "platform_version": settings.PLATFORM_VERSION,
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "default_workspace_slug": settings.DEFAULT_WORKSPACE_SLUG,
        "map_tile_url": settings.MAP_TILE_URL,
        "map_tile_attribution": settings.MAP_TILE_ATTRIBUTION,
        "map_light_style": _light_style(),
        "map_vector_style_url_light": settings.MAP_VECTOR_STYLE_URL_LIGHT.strip(),
        "map_dark_style": _dark_style(dark_tile_url),
        "map_vector_style_url_dark": settings.MAP_VECTOR_STYLE_URL_DARK.strip(),
        "map_tile_url_dark": dark_tile_url,
        "map_tile_attribution_dark": settings.MAP_TILE_ATTRIBUTION_DARK,
        "map_tile_url_satellite": settings.MAP_TILE_URL_SATELLITE,
        "map_tile_attribution_satellite": settings.MAP_TILE_ATTRIBUTION_SATELLITE,
        "project_repo_url": settings.PROJECT_REPO_URL,
        "project_release_url": settings.PROJECT_RELEASE_URL,
        "is_admin": getattr(request, "is_admin", False),
    }
