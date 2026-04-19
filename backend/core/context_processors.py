"""Template context processor exposing platform-level state."""

from django.conf import settings


def platform_context(request):
    return {
        "platform_version": settings.PLATFORM_VERSION,
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "default_workspace_slug": settings.DEFAULT_WORKSPACE_SLUG,
        "map_tile_url": settings.MAP_TILE_URL,
        "map_tile_attribution": settings.MAP_TILE_ATTRIBUTION,
        "project_repo_url": settings.PROJECT_REPO_URL,
        "project_release_url": settings.PROJECT_RELEASE_URL,
        "is_admin": getattr(request, "is_admin", False),
    }
