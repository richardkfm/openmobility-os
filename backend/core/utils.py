"""Shared helpers used by multiple apps.

Keep this module small — if a helper is only used by one app, it belongs there.
"""

from django.shortcuts import get_object_or_404


def get_active_workspace(slug: str):
    """Fetch an active workspace by slug or 404.

    Imported lazily so this module stays free of cross-app import cycles
    during Django startup.
    """
    from workspaces.models import Workspace

    return get_object_or_404(Workspace, slug=slug, is_active=True)
